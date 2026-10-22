# Speech fixture

`speech.wav` is an original synthetic utterance generated with Windows System.Speech:

> Please review the code and add tests for the new feature.

It is stored as 16 kHz mono PCM for repeatable input. Integration tests download/cache Whisper base and assert nonempty text and word timestamps, without requiring exact transcription.
