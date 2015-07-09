#!/usr/bin/env python
"""Chainer example: autoencoder of a solar image.
"""

# c.f.
# http://nonbiri-tereka.hatenablog.com/entry/2015/06/21/220506
# http://qiita.com/kenmatsu4/items/99d4a54d5a57405ecaf8

import argparse

import numpy as np
import operator
import re
import six
import subprocess
import random

import chainer
from chainer import computational_graph as c
from chainer import cuda, Variable, FunctionSet, optimizers
import chainer.functions as F
from chainer import optimizers

parser = argparse.ArgumentParser(description='Chainer example: MNIST')
parser.add_argument('--gpu', '-g', default=-1, type=int,
                    help='GPU ID (negative value indicates CPU)')
args = parser.parse_args()

logfn = 'log-training.txt'

subprocess.call('rm '+ logfn,shell=True)

def zoom_x2(batch):
    shape = batch.data.shape
    channel_shape = shape[0:-2]
    height, width = shape[-2:]
 
    volume = reduce(operator.mul,shape,1)
 
    b1 = F.reshape(batch,(volume,1))
    b2 = F.concat([b1,b1],1)
 
    b3 = F.reshape(b2,(volume/width,2*width))
    b4 = F.concat([b3,b3],1)
 
    return F.reshape(b4, channel_shape + (2*height ,) + (2*width ,))



gpu_flag=(args.gpu >= 0)

# load the numpy 2D arrays located under the folder.
p=subprocess.Popen('find scaled-256/',shell=True, stdout=subprocess.PIPE)
stdout, _ = p.communicate()

sun_data = []

for fn in stdout.split('\n')[0:10]:
    if not re.search('\.npy$',fn) : continue
    sun_data.append(np.load(fn))

if len(sun_data)==0:
    # where no data is available, add a dummy data for debugging
    for i in range(10):
        x=32*[0.333*i*i]
        xy=32*[x]
        sun_data.append(xy)


model=chainer.FunctionSet(
    conv1 = F.Convolution2D(4,8,3,stride=1,pad=1),
    conv2 = F.Convolution2D(8,16,3,stride=1,pad=1),
    conv9 = F.Convolution2D(16,1,3,stride=1,pad=1),
)



if gpu_flag:
    cuda.init(0)
    model.to_gpu()



def forward(x_data,y_data,train=True):
    x = Variable(x_data, volatile = not train)
    y = Variable(y_data, volatile = not train)
    h1 = F.dropout(F.leaky_relu(model.conv1(x)),  train=train)
    h2 = F.dropout(F.leaky_relu(model.conv2(h1)),  train=train)
    y_pred = model.conv9(h2)
    return F.mean_squared_error(y,y_pred)




optimizer = optimizers.Adam()
optimizer.setup(model.collect_parameters())

for epoch in range(1000000):
    batch_input = []; batch_output = []
    for i in range(1):
        n = 4
        start = random.randrange(len(sun_data)-n-1)
        batch_input.append(sun_data[start:start+n])
        batch_output.append(sun_data[start+n])

    batch_input=np.array(batch_input)
    batch_output=np.array(batch_output)
    if gpu_flag :
        batch_input = cuda.to_gpu(batch_input)
        batch_output = cuda.to_gpu(batch_output)

    optimizer.zero_grads()
    loss = forward(batch_input, batch_output, train=True)
    loss.backward()
    optimizer.update()

    print epoch,loss.data

    with(open(logfn,'a')) as fp:
        fp.write('{} {}\n'.format(epoch,loss.data))
