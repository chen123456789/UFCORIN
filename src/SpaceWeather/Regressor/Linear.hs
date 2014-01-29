{-# LANGUAGE FlexibleContexts, FlexibleInstances, MultiParamTypeClasses, OverloadedStrings, TemplateHaskell, TypeSynonymInstances #-}
module SpaceWeather.Regressor.Linear where

import qualified Data.Aeson.TH as Aeson

data LinearOption = LinearOption  deriving (Eq, Ord, Show, Read)
Aeson.deriveJSON Aeson.defaultOptions ''LinearOption

