### Overview

Multi Variant Fishtest, is a distributed tasks queue for testing new ideas and improvements for multi variant chess engine through self playing. The main instance for [Multi Variant Stockfish](https://github.com/ddugovic/Stockfish) is:

http://35.161.250.236:6543/tests

Developers submit patches with new ideas and improvements for the chess variant, CPU contributors install a fishtest worker on their computers to play some chess games in the background to help the developers testing the patches.

The fishtest worker:
- automatically connects to the server to download: a chess opening book, the [cutechess-cli](https://github.com/ddugovic/Stockfish/wiki/How-To-build-cutechess-with-Qt-5-static) chess game manager and the chess engine sources (for the actual master and for the patch with the new idea) that will be compiled according to the type of worker platform.
- starts a batch of games using cutechess-cli.
- uploads the games results on the server.

The fishtest server:
- provides several test templates to generate tests for the patches.
- manages the queue of the tests according customizable prorities.
- computes several probabilistic values from the game results sent by the workers.
- updates and publishes the results of ongoing tests.
- stops tests according some bounds and publishes the final tests results.

#### Worker and Server setup

Follow these instructions to setup:
- a [Multi Variant Fishtest worker on Linux](worker-setup-linux.md)
- a [Multi Variant Fishtest worker on Windows](worker-setup-windows.md)
- a [Multi Variant Fishtest server on Ubuntu](server-setup.md)