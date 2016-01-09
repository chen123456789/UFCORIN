#!/usr/bin/env python
import pickle,subprocess
import numpy as np
import os
import math
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt



import chainer
from chainer import computational_graph
from chainer import cuda
from chainer import optimizers
from chainer import serializers
from chainer import Variable
from chainer.utils import type_check
from chainer import function

import chainer.functions as F
import chainer.links as L


import numpy



image_dir = './images'
out_image_dir = './out_images'
out_model_dir = './out_models'


nz = 100          # # of dim for Z
n_signal = 2 # # of signal
zw=15 # size of in-vivo z patch
zh=15
batchsize=1
n_epoch=10000
n_train=200000
image_save_interval = 200


def average(x):
    return F.sum(x/x.data.size)

def dual_log(scale, x):
    x2 = x/scale
    #not implemented error!
    #return F.where(x>0,F.log(x2+1),-F.log(1-x2))
    return np.log(1+np.maximum(0,x2))-np.log(1+np.maximum(0,-x2))


class ELU(function.Function):

    """Exponential Linear Unit."""
    # https://github.com/muupan/chainer-elu

    def __init__(self, alpha=1.0):
        self.alpha = numpy.float32(alpha)

    def check_type_forward(self, in_types):
        type_check.expect(in_types.size() == 1)
        x_type, = in_types

        type_check.expect(
            x_type.dtype == numpy.float32,
        )

    def forward_cpu(self, x):
        y = x[0].copy()
        neg_indices = x[0] < 0
        y[neg_indices] = self.alpha * (numpy.exp(y[neg_indices]) - 1)
        return y,

    def forward_gpu(self, x):
        y = cuda.elementwise(
            'T x, T alpha', 'T y',
            'y = x >= 0 ? x : alpha * (exp(x) - 1)', 'elu_fwd')(
                x[0], self.alpha)
        return y,

    def backward_cpu(self, x, gy):
        gx = gy[0].copy()
        neg_indices = x[0] < 0
        gx[neg_indices] *= self.alpha * numpy.exp(x[0][neg_indices])
        return gx,

    def backward_gpu(self, x, gy):
        gx = cuda.elementwise(
            'T x, T gy, T alpha', 'T gx',
            'gx = x >= 0 ? gy : gy * alpha * exp(x)', 'elu_bwd')(
                x[0], gy[0], self.alpha)
        return gx,


def elu(x, alpha=1.0):
    """Exponential Linear Unit function."""
    # https://github.com/muupan/chainer-elu
    return ELU(alpha=alpha)(x)




class Generator(chainer.Chain):
    def __init__(self):
        super(Generator, self).__init__(
            dc0z = L.Deconvolution2D(nz, 512, 8, stride=4, wscale=0.02*math.sqrt(nz)),
            dc0s = L.Deconvolution2D(n_signal, 512, 8, stride=4, wscale=0.02*math.sqrt(n_signal)),
            dc1 = L.Deconvolution2D(512, 256, 4, stride=2, pad=1, wscale=0.02*math.sqrt(4*4*512)),
            dc2 = L.Deconvolution2D(256, 128, 4, stride=2, pad=1, wscale=0.02*math.sqrt(4*4*256)),
            dc3 = L.Deconvolution2D(128, 64, 4, stride=2, pad=1, wscale=0.02*math.sqrt(4*4*128)),
            dc4 = L.Deconvolution2D(64, 1, 4, stride=2, pad=1, wscale=0.02*math.sqrt(4*4*64)),
            bn0 = L.BatchNormalization(512),
            bn1 = L.BatchNormalization(256),
            bn2 = L.BatchNormalization(128),
            bn3 = L.BatchNormalization(64),
        )
        
    def __call__(self, z, z_signal, test=False):
        h  = F.relu(self.bn0(self.dc0z(z) + self.dc0s(z_signal), test=test))
        h = F.relu(self.bn1(self.dc1(h), test=test))
        h = F.relu(self.bn2(self.dc2(h), test=test))
        h = F.relu(self.bn3(self.dc3(h), test=test))
        x = (self.dc4(h))
        return x

class Encoder(chainer.Chain):
    def __init__(self):
        super(Encoder, self).__init__(
            c0 = L.Convolution2D(1, 64, 4, stride=2, pad=1, wscale=0.02*math.sqrt(4*4*3)),
            c1 = L.Convolution2D(64, 128, 4, stride=2, pad=1, wscale=0.02*math.sqrt(4*4*64)),
            c2 = L.Convolution2D(128, 256, 4, stride=2, pad=1, wscale=0.02*math.sqrt(4*4*128)),
            c3 = L.Convolution2D(256, 512, 4, stride=2, pad=1, wscale=0.02*math.sqrt(4*4*256)),
            cz = L.Convolution2D(512, nz , 8, stride=4, wscale=1.0*math.sqrt(8*8*512)),

            bn0 = L.BatchNormalization(64),
            bn1 = L.BatchNormalization(128),
            bn2 = L.BatchNormalization(256),
            bn3 = L.BatchNormalization(512),
        )
        
    def __call__(self, x, test=False):
        print x.data.shape
        h = elu(self.c0(x))     # no bn because images from generator will katayotteru?
        h = elu(self.bn1(self.c1(h), test=test))
        h = elu(self.bn2(self.c2(h), test=test))
        h = elu(self.bn3(self.c3(h), test=test))
        return self.cz(h)


class Discriminator(chainer.Chain):
    def __init__(self):
        super(Discriminator, self).__init__(
            c0 = L.Convolution2D(1, 64, 4, stride=2, pad=1, wscale=0.02*math.sqrt(4*4*3)),
            c1 = L.Convolution2D(64, 128, 4, stride=2, pad=1, wscale=0.02*math.sqrt(4*4*64)),
            c2 = L.Convolution2D(128, 256, 4, stride=2, pad=1, wscale=0.02*math.sqrt(4*4*128)),
            c3 = L.Convolution2D(256, 512, 4, stride=2, pad=1, wscale=0.02*math.sqrt(4*4*256)),
            cz = L.Convolution2D(512, 2, 8, stride=4,wscale=0.02*math.sqrt(6*6*512)),
            bn0 = L.BatchNormalization(64),
            bn1 = L.BatchNormalization(128),
            bn2 = L.BatchNormalization(256),
            bn3 = L.BatchNormalization(512),
        )
        
    def __call__(self, x, test=False, compare=None):
        h = elu(self.c0(x))     # no bn because images from generator will katayotteru?
        h = elu(self.bn1(self.c1(h), test=test))
        h = elu(self.bn2(self.c2(h), test=test))
        h = elu(self.bn3(self.c3(h), test=test))
        if compare is not None:
            h2 = elu(self.c0(compare))            
            h2 = elu(self.bn1(self.c1(h2), test=test))
            h2 = elu(self.bn2(self.c2(h2), test=test))
            h2 = elu(self.bn3(self.c3(h2), test=test))
            
            return average((h-h2)**2)

        l = F.sum(self.cz(h),axis=(2,3))
        return l



def load_image():
    while True:
        try:
            year  = 2011 + np.random.randint(4)
            month = 1 + np.random.randint(12)
            day   = 1 + np.random.randint(32)
            hour  = np.random.randint(24)
            minu  = np.random.randint(5)*12
    
            subprocess.call('rm work/*',shell=True)
            cmd = 'aws s3 cp "s3://sdo/aia193/720s-x1024/{:04}/{:02}/{:02}/{:02}{:02}.npz" work/img.npz --region us-west-2 --quiet'.format(year,month,day,hour,minu)
            print(cmd)
            subprocess.call(cmd, shell=True)
            ret = dual_log(500, np.load('work/img.npz')['img'])
            return np.reshape(ret, (1,1,1024,1024))
        except:
            continue

def position_signal(i,w):
    ww = w/2
    return (i - ww)/float(ww)


def train_vaegan_labeled(gen, enc, dis, epoch0=0):
    o_gen = optimizers.Adam(alpha=0.0002, beta1=0.5)
    o_enc = optimizers.Adam(alpha=0.0002, beta1=0.5)
    o_dis = optimizers.Adam(alpha=0.0002, beta1=0.5)
    o_gen.setup(gen)
    o_enc.setup(enc)
    o_dis.setup(dis)
    o_gen.add_hook(chainer.optimizer.WeightDecay(0.00001))
    o_enc.add_hook(chainer.optimizer.WeightDecay(0.00001))
    o_dis.add_hook(chainer.optimizer.WeightDecay(0.00001))


    
    for epoch in xrange(epoch0,n_epoch):
        perm = np.random.permutation(n_train)
        sum_l_dis = np.float32(0)
        sum_l_gen = np.float32(0)
        
        for i in xrange(0, n_train, batchsize):
            # discriminator
            # 0: from dataset
            # 1: from noise

            #print "load image start ", i
            x_train_data = load_image()
            x_train = Variable(cuda.to_gpu(x_train_data))
            

            # generate prior and signal
            z_prior = np.random.standard_normal((batchsize, nz, zh, zw)).astype(np.float32)
            z_signal =np.zeros((batchsize, 2, zh, zw)).astype(np.float32)
            # normalize the prior, and embed the position signal in z vector
            for y in range (zh):
                for x in range (zw):
                    z_stripe = z_prior[:,:,y,x]
                    z_norm = np.sum(z_stripe**2)
                    z_stripe *= np.sqrt(nz / z_norm)
                    z_prior[:,:,y,x] = z_stripe
                    z_signal[:,0,y,x] = position_signal(x, zw)
                    z_signal[:,1,y,x] = position_signal(y, zh)
            z_prior = Variable(cuda.to_gpu(z_prior))
            z_signal = Variable(cuda.to_gpu(z_signal))

            
            # use encoder
            z_enc = enc(x_train)
            x_vae = gen(z_enc,z_signal)
            x_prior = gen(z_prior,z_signal)

            yl_train  = dis(x_train)
            yl_vae    = dis(x_vae)
            yl_prior  = dis(x_prior)
            yl_dislike = dis(x_vae, compare=x_train)

            l_prior = average(F.sum(z_enc**2,axis=1) - nz)**2

            L_gen  = F.softmax_cross_entropy(yl_vae, Variable(xp.zeros(batchsize, dtype=np.int32)))
            L_gen += F.softmax_cross_entropy(yl_prior, Variable(xp.zeros(batchsize, dtype=np.int32)))
            L_gen += yl_dislike

            L_enc  = F.softmax_cross_entropy(yl_vae, Variable(xp.zeros(batchsize, dtype=np.int32)))
            L_enc += l_prior
            L_enc += yl_dislike

            L_dis  = 2*F.softmax_cross_entropy(yl_train, Variable(xp.zeros(batchsize, dtype=np.int32)))
            L_dis +=   F.softmax_cross_entropy(yl_vae, Variable(xp.ones(batchsize , dtype=np.int32)))           
            L_dis +=   F.softmax_cross_entropy(yl_prior, Variable(xp.ones(batchsize , dtype=np.int32)))           
            
            for x in [yl_train, yl_vae, yl_prior]:
                print x.data.get()
            print [x.data.get() for x in [L_gen, L_enc, L_dis, yl_dislike, l_prior]]

            o_gen.zero_grads()
            L_gen.backward()
            o_gen.update()
            
            o_enc.zero_grads()
            L_enc.backward()
            o_enc.update()
            
            o_dis.zero_grads()
            L_dis.backward()
            o_dis.update()
            
            L_gen.unchain_backward()
            L_enc.unchain_backward()
            L_dis.unchain_backward()
            
            #print "backward done"
            if True:
                plt.rcParams['figure.figsize'] = (36.0,12.0)
                plt.clf()
                plt.subplot(1,3,1)
                plt.imshow(x_train.data.get()[0,0], vmin=0.0, vmax=2.0)
                plt.subplot(1,3,2)
                plt.imshow(x_vae.data.get()[0,0],vmin=0.0,  vmax=2.0)
                plt.subplot(1,3,3)
                plt.imshow(x_prior.data.get()[0,0], vmin=0.0, vmax=2.0)
                fn0 = '%s/latest.png'%(out_image_dir)
                fn1 = '%s/vis_%02d_%06d.png'%(out_image_dir, epoch,i)
                plt.savefig(fn0)
                if i%image_save_interval==0:
                    subprocess.call("cp {} {}".format(fn0,fn1), shell=True)
                
        serializers.save_hdf5("%s/vaegan_model_dis_%d.h5"%(out_model_dir, epoch),dis)
        serializers.save_hdf5("%s/vaegan_state_dis_%d.h5"%(out_model_dir, epoch),o_dis)
        serializers.save_hdf5("%s/vaegan_model_gen_%d.h5"%(out_model_dir, epoch),gen)
        serializers.save_hdf5("%s/vaegan_state_gen_%d.h5"%(out_model_dir, epoch),o_gen)
        serializers.save_hdf5("%s/vaegan_model_enc_%d.h5"%(out_model_dir, epoch),enc)
        serializers.save_hdf5("%s/vaegan_state_enc_%d.h5"%(out_model_dir, epoch),o_enc)
        print('epoch end', epoch)



xp = cuda.cupy
cuda.get_device(0).use()

gen = Generator()
enc = Encoder()
dis = Discriminator()
gen.to_gpu()
enc.to_gpu()
dis.to_gpu()


try:
    os.mkdir(out_image_dir)
    os.mkdir(out_model_dir)
except:
    pass

train_vaegan_labeled(gen, enc, dis)