#!/usr/bin/env stack
-- stack --resolver lts-12.5 script

-- git-br.hs -- Git branch with tabular alignment.
-- Written in 2018 by Ruud van Asseldonk.
--
-- To the extent possible under law, the author has dedicated all copyright and
-- related neighbouring rights to this software to the public domain worldwide.
-- See the CC0 dedication at https://creativecommons.org/publicdomain/zero/1.0/.

-- Expects output from "git branch" with the following --format:
--
--     %(HEAD)%00%(objectname:short=7)%00%(refname)%00%(refname:short)%00
--     %(upstream)%00%(upstream:short)%00%(upstream:track)
--
-- See also the alias line in my .gitconfig, and git-br.py

{-# LANGUAGE DeriveFunctor #-}
{-# LANGUAGE DeriveAnyClass #-}
{-# LANGUAGE StandaloneDeriving #-}

import qualified Data.Set as Set

data Branch a = Branch
  { head :: a
  , hashShort :: a
  , refname :: a
  , refnameShort :: a
  , upstream :: a
  , upstreamShort :: a
  , upstreamTrack :: a
  } deriving (Eq, Ord, Show, Functor)

deriving instance Semigroup a => Semigroup (Branch a)
deriving instance Monoid a => Monoid (Branch a)

parseBranch :: String -> Branch String
parseBranch =
  let
    splitNull str = let (word, more) = break (== '\0') str in word : splitNull (tail more)
    makeBranch [c0, c1, c2, c3, c4, c5, c6] = Branch c0 c1 c2 c3 c4 c5 c6
  in
    makeBranch . take 7 . splitNull

data Node a = Node (Branch a) [Node a] deriving Show

getChildren :: Eq a => [Branch a] -> a -> [Node a]
getChildren branches parentRefname =
  let
    makeNode branch = Node branch $ getChildren branches $ refname branch
    isChild branch = parentRefname == upstream branch
  in
    fmap makeNode $ filter isChild branches

flatten :: String -> [Node String] -> [Branch String]
flatten indent =
  let
    indented branch = branch { refnameShort = indent ++ refnameShort branch }
    flattenNode (Node branch children) =
      indented branch : flatten (indent ++ "  ") children
  in
    concatMap flattenNode

gitBr :: [String] -> [String]
gitBr lines =
  let
    branches = fmap parseBranch lines
    refnames = Set.fromList $ fmap refname branches
    fixUpstream branch =
      if upstream branch `Set.member` refnames
        then branch
        else branch { upstream = "" }
    branchTree = flatten "" $ getChildren (fmap fixUpstream branches) ""
    columns = foldMap (fmap (:[])) branchTree
  in
    [show columns]

main :: IO ()
main = interact (unlines . gitBr . lines)
