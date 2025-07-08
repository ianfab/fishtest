### Overview

Variant Fishtest, is a distributed task queue to test new ideas and improvements for chess variant engines through self playing. The main instance for [Multi-Variant Stockfish](https://github.com/ddugovic/Stockfish) and [Fairy-Stockfish](https://github.com/ianfab/Fairy-Stockfish) is:

http://variantfishtest.org/tests (currently offline)

Developers submit patches with new ideas and improvements for the engine, and CPU contributors install a fishtest worker on their computers to let the engine play games in the background in order to help developers test their patches.

The fishtest worker:
- automatically connects to the server to download: a chess opening book, the [cutechess-cli](https://github.com/ddugovic/Stockfish/wiki/How-To-build-cutechess-with-Qt-5-static) chess game manager and the chess engine sources (for the actual master and for the patch with the new idea) that will be compiled according to the type of worker platform.
- starts a batch of games using cutechess-cli.
- uploads the game results to the server.

The fishtest server:
- provides several test templates to generate tests for the patches.
- manages the testing queue according to customizable priorities.
- computes statistics from the game results sent by the workers.
- updates and publishes the results of ongoing tests.
- stops tests according to the selected stopping rule and publishes the final test results.

To get more information please visit the [Variant Fishtest Wiki](https://github.com/ianfab/fishtest/wiki)
