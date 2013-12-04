{-# LANGUAGE TupleSections #-}
module Main where

import Control.Monad
import Data.List
import qualified Data.Map.Strict as Map
import Data.Maybe
import qualified Data.Text as T
import qualified Data.Text.IO as T
import Safe
import System.IO
import System.IO.Unsafe 
import System.Process
import Text.Printf

import SpaceWeather.Text
import SpaceWeather.TimeLine

-- the filename to be forecasted.
fnForecast :: FilePath
fnForecast = "forecast/forecast-goes-24.txt"

goesForecastCurve :: TimeLine Double
goesForecastCurve = unsafePerformIO $ do
  str <- T.readFile fnForecast
  let xss :: [[T.Text]]
      xss = map T.words $ T.lines str
      
      parseLine :: [T.Text] -> Maybe (TimeBin, Double)
      parseLine ws = do
        t <- readAt ws 1
        v <- readAt ws 4
        return (t,v)
  return $ Map.fromList $ catMaybes $ map parseLine xss

data FeatureCurve
  = FeatureCurve
  { tag :: String
  , range :: (Double, Double)
  , timeLine :: TimeLine Double
  }
  

featureCurves :: [FeatureCurve]
featureCurves = unsafePerformIO $ do 
  str <- readProcess "ls" [dir1] ""
  let fns0 = words str
      fns1 = map (dir1++) $ fns0
      fns2 = map (dir2++) $ fns0
  zipWithM go fns1 fns2      

  where
    dir1 = "wavelet-features-bsplC/"
    dir2 = "work/"    
    
    go fn1 fn2 = do
      hPutStrLn stderr $ printf "processing %s..." fn1
      str1 <- T.readFile fn1
      
      let tl :: TimeLine Double
          tl = Map.fromList $ catMaybes $ map parse $ map T.words $ T.lines str1

          parse :: [T.Text] -> Maybe (TimeBin, Double)
          parse ws = do
            t <- readAt ws 2
            v <- readAt ws 4
            return (t,v)
      
          vals :: [Double]
          vals = sort $ Map.elems tl
          
          small =  maybe 1 id $ headMay $ drop (length vals `div` 100) vals
          large =  maybe 10 id $ headMay $ drop (length vals `div` 100) $ reverse vals
          
          mixTL = Map.intersectionWith (,) goesForecastCurve tl
          
      T.writeFile fn2 $ T.unlines $ [T.pack $ printf "%f %f" v1 v2 | (_,(v1,v2)) <- Map.toList mixTL]
      return $ FeatureCurve {range = (small,large), tag = fn2, timeLine = tl}
      
type TrainDatum = (Int, [Double])
type TrainData = TimeLine TrainDatum

trainData :: TrainData
trainData = foldl go t0 $ reverse featureCurves      
  where
    t0 :: TrainData
    t0 = Map.map ((, []) . toClass) goesForecastCurve 

    toClass :: Double -> Int                                            
    toClass x
      | x < 1e-6 = 0
      | x < 1e-5 = 1
      | x < 1e-4 = 2
      | otherwise =3
    
    go :: TrainData -> FeatureCurve -> TrainData
    go x y = Map.intersectionWith go2 x (timeLine y)
    
    go2 :: TrainDatum -> Double -> TrainDatum
    go2 (i,xs) x = (i, x:xs)

pprint :: TrainDatum -> T.Text
pprint (c,xs) = T.pack $ printf "%d %s" c xsstr
  where
    xsstr :: String
    xsstr = unwords $ zipWith (printf "%d:%f") [1 :: Int ..] xs

plotCmd :: String
plotCmd = unlines $
  [ "set term postscript enhanced color solid 20"
  , "set log xy"
  , "set out 'test.eps'"
  , "set xlabel 'GOES flux (24hour forecast max)'"
  , "set ylabel 'feature vector component'"
  , "set xrange [1e-8:1e-3]" 
  ] ++ map go featureCurves
  where
    go :: FeatureCurve -> String
    go fc = 
      let (small,large) = range fc
          fn = tag fc
      in unlines
      [ printf "set title '%s'" fn
      , printf "set yrange [%f:%f]" small large
      , printf "plot '%s' u 1:2" fn]



main :: IO ()
main = do
  _ <- readProcess "gnuplot" [] plotCmd
  
  let td = Map.elems trainData
      n  = length td
      (td2011, td2012) = splitAt (div n 2) td
  
  hPutStrLn stderr "create corpus 2011..."
  T.writeFile "corpus-2011.txt" $ T.unlines $ map pprint $ td2011
  hPutStrLn stderr "create corpus 2012..."
  T.writeFile "corpus-2012.txt" $ T.unlines $ map pprint $ td2012
  return ()

