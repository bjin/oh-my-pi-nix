{-# LANGUAGE RecordWildCards #-}
module Crash (parseMessage) where

-- Testcase for the tree-sitter-haskell strict-aliasing heap corruption.
--
-- Requirements this file must keep satisfying to be a valid `omp read` probe:
--   * >= 100 total lines   -> clears the `read.summarize.minTotalLines` gate,
--                             so the read tool actually calls summarizeCode()
--   * syntactically valid  -> proves the crash is not an error-recovery quirk
--                             (tree-sitter reports has_error() == false here)
--   * <= 2000 lines / 256 KiB -> stays under MAX_SUMMARY_LINES / MAX_SUMMARY_BYTES
--
-- The trigger is the `case` alternative below: a constructor pattern wrapping a
-- record pattern that contains BOTH a list pattern and a nested record pattern
-- using a RecordWildCards `{..}`. That shape drives the external scanner's
-- layout/indentation Array through a realloc inside `array_push`.

data Header = Header
  { identifier :: Int
  , flags      :: Int
  }

data Question = Question
  { qname :: String
  , qtype :: Int
  }

data Message = Message
  { question :: [Question]
  , header   :: Header
  }

data Request = Request
  { reqName :: String
  , reqType :: Int
  }

parseMessage0 :: Either String Message -> Maybe Request
parseMessage0 msg =
    case msg of
        Right (Message { question = [q], header = Header {..} }) ->
            Just Request { reqName = qname q, reqType = identifier }
        _ -> Nothing

parseMessage1 :: Either String Message -> Maybe Request
parseMessage1 msg =
    case msg of
        Right (Message { question = [q], header = Header {..} }) ->
            Just Request { reqName = qname q, reqType = identifier }
        _ -> Nothing

parseMessage2 :: Either String Message -> Maybe Request
parseMessage2 msg =
    case msg of
        Right (Message { question = [q], header = Header {..} }) ->
            Just Request { reqName = qname q, reqType = identifier }
        _ -> Nothing

parseMessage3 :: Either String Message -> Maybe Request
parseMessage3 msg =
    case msg of
        Right (Message { question = [q], header = Header {..} }) ->
            Just Request { reqName = qname q, reqType = identifier }
        _ -> Nothing

parseMessage4 :: Either String Message -> Maybe Request
parseMessage4 msg =
    case msg of
        Right (Message { question = [q], header = Header {..} }) ->
            Just Request { reqName = qname q, reqType = identifier }
        _ -> Nothing

parseMessage5 :: Either String Message -> Maybe Request
parseMessage5 msg =
    case msg of
        Right (Message { question = [q], header = Header {..} }) ->
            Just Request { reqName = qname q, reqType = identifier }
        _ -> Nothing

parseMessage6 :: Either String Message -> Maybe Request
parseMessage6 msg =
    case msg of
        Right (Message { question = [q], header = Header {..} }) ->
            Just Request { reqName = qname q, reqType = identifier }
        _ -> Nothing

parseMessage7 :: Either String Message -> Maybe Request
parseMessage7 msg =
    case msg of
        Right (Message { question = [q], header = Header {..} }) ->
            Just Request { reqName = qname q, reqType = identifier }
        _ -> Nothing

parseMessage8 :: Either String Message -> Maybe Request
parseMessage8 msg =
    case msg of
        Right (Message { question = [q], header = Header {..} }) ->
            Just Request { reqName = qname q, reqType = identifier }
        _ -> Nothing

parseMessage9 :: Either String Message -> Maybe Request
parseMessage9 msg =
    case msg of
        Right (Message { question = [q], header = Header {..} }) ->
            Just Request { reqName = qname q, reqType = identifier }
        _ -> Nothing

parseMessage10 :: Either String Message -> Maybe Request
parseMessage10 msg =
    case msg of
        Right (Message { question = [q], header = Header {..} }) ->
            Just Request { reqName = qname q, reqType = identifier }
        _ -> Nothing

parseMessage11 :: Either String Message -> Maybe Request
parseMessage11 msg =
    case msg of
        Right (Message { question = [q], header = Header {..} }) ->
            Just Request { reqName = qname q, reqType = identifier }
        _ -> Nothing

parseMessage12 :: Either String Message -> Maybe Request
parseMessage12 msg =
    case msg of
        Right (Message { question = [q], header = Header {..} }) ->
            Just Request { reqName = qname q, reqType = identifier }
        _ -> Nothing

parseMessage13 :: Either String Message -> Maybe Request
parseMessage13 msg =
    case msg of
        Right (Message { question = [q], header = Header {..} }) ->
            Just Request { reqName = qname q, reqType = identifier }
        _ -> Nothing

parseMessage :: Either String Message -> Maybe Request
parseMessage = parseMessage0
