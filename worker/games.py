from __future__ import absolute_import, print_function

import datetime
import glob
import json
import os
import platform
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from base64 import b64decode
from zipfile import ZipFile

import requests

try:
    from Queue import Empty, Queue
except ImportError:
    from queue import Empty, Queue  # python 3.x

# Global because is shared across threads
old_stats = {"wins": 0, "losses": 0, "draws": 0, "crashes": 0, "time_losses": 0}

IS_WINDOWS = "windows" in platform.system().lower()


def is_windows_64bit():
    if "PROCESSOR_ARCHITEW6432" in os.environ:
        return True
    return os.environ["PROCESSOR_ARCHITECTURE"].endswith("64")


def is_64bit():
    if IS_WINDOWS:
        return is_windows_64bit()
    return "64" in platform.architecture()[0]


HTTP_TIMEOUT = 5.0

FISHCOOKING_URL = "https://github.com/ianfab/FishCooking"
BOOKS_URL = "https://github.com/ianfab/books"
EXE_SUFFIX = ".exe" if IS_WINDOWS else ""
MAKE_CMD = "make COMP=mingw " if IS_WINDOWS else "make COMP=gcc "


def github_api(repo):
    """Convert from https://github.com/<user>/<repo>
    To https://api.github.com/repos/<user>/<repo>"""
    return repo.replace("https://github.com", "https://api.github.com/repos")


def verify_signature(engine, signature, remote, payload, concurrency):
    if concurrency > 1:
        with open(os.devnull, "wb") as dev_null:
            busy_process = subprocess.Popen(
                [engine],
                stdin=subprocess.PIPE,
                stdout=dev_null,
                universal_newlines=True,
                bufsize=1,
                close_fds=not IS_WINDOWS,
            )

        busy_process.stdin.write(
            "setoption name Threads value {}\n".format(concurrency - 1)
        )
        busy_process.stdin.write("go infinite\n")
        busy_process.stdin.flush()

    try:
        bench_sig = ""
        print("Verifying signature of {} ...".format(os.path.basename(engine)))
        with open(os.devnull, "wb") as dev_null:
            p = subprocess.Popen(
                [engine, "bench"],
                stderr=subprocess.PIPE,
                stdout=dev_null,
                universal_newlines=True,
                bufsize=1,
                close_fds=not IS_WINDOWS,
            )
        for line in iter(p.stderr.readline, ""):
            if "Nodes searched" in line:
                bench_sig = line.split(": ")[1].strip()
            if "Nodes/second" in line:
                bench_nps = float(line.split(": ")[1].strip())

        p.wait()
        p.stderr.close()
        if p.returncode != 0:
            raise Exception("Bench exited with non-zero code {}".format(p.returncode))

        if int(bench_sig) != int(signature):
            message = "Wrong bench in {} Expected: {} Got: {}".format(
                os.path.basename(engine), signature, bench_sig
            )
            payload["message"] = message
            requests.post(
                remote + "/api/stop_run",
                data=json.dumps(payload),
                headers={"Content-type": "application/json"},
                timeout=HTTP_TIMEOUT,
            )
            raise Exception(message)

    finally:
        if concurrency > 1:
            busy_process.communicate("quit\n")
            busy_process.stdin.close()

    return bench_nps


def setup(item, testing_dir, url=FISHCOOKING_URL, branch="setup"):
    """Download item from FishCooking to testing_dir"""
    tree = requests.get(
        github_api(url) + "/git/trees/" + branch, timeout=HTTP_TIMEOUT
    ).json()
    for blob in tree["tree"]:
        if blob["path"] == item:
            print("Downloading {} ...".format(item))
            blob_json = requests.get(blob["url"], timeout=HTTP_TIMEOUT).json()
            with open(os.path.join(testing_dir, item), "wb+") as f:
                f.write(b64decode(blob_json["content"]))
            break
    else:
        raise Exception("Item {} not found".format(item))


def gcc_props():
    """Parse the output of g++ -Q -march=native --help=target and extract the available properties"""
    p = subprocess.Popen(
        ["g++", "-Q", "-march=native", "--help=target"],
        stdout=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1,
        close_fds=not IS_WINDOWS,
    )

    flags = []
    arch = "None"
    for line in iter(p.stdout.readline, ""):
        if "[enabled]" in line:
            flags.append(line.split()[0])
        if "-march" in line and len(line.split()) == 2:
            arch = line.split()[1]

    p.wait()
    p.stdout.close()

    if p.returncode != 0:
        raise Exception(
            "g++ target query failed with return code {}".format(p.returncode)
        )

    return {"flags": flags, "arch": arch}


def make_targets():
    """Parse the output of make help and extract the available targets"""
    p = subprocess.Popen(
        ["make", "help"],
        stdout=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1,
        close_fds=not IS_WINDOWS,
    )

    targets = []
    read_targets = False

    for line in iter(p.stdout.readline, ""):
        if "Supported compilers:" in line:
            read_targets = False
        if read_targets and len(line.split()) > 1:
            targets.append(line.split()[0])
        if "Supported archs:" in line:
            read_targets = True

    p.wait()
    p.stdout.close()

    if p.returncode != 0:
        raise Exception("make help failed with return code {}".format(p.returncode))

    return targets


def find_arch_string():
    """Find the best ARCH=... string based on the cpu/g++ capabilities and Makefile targets"""

    targets = make_targets()

    props = gcc_props()

    if is_64bit():
        if (
            "-mavx512vnni" in props["flags"]
            and "-mavx512dq" in props["flags"]
            and "-mavx512f" in props["flags"]
            and "-mavx512bw" in props["flags"]
            and "-mavx512vl" in props["flags"]
            and "x86-64-vnni256" in targets
        ):
            res = "x86-64-vnni256"
        elif (
            "-mbmi2" in props["flags"]
            and "x86-64-bmi2" in targets
            and not props["arch"] in ["znver1", "znver2"]
        ):
            res = "x86-64-bmi2"
        elif "-mavx2" in props["flags"] and "x86-64-avx2" in targets:
            res = "x86-64-avx2"
        elif (
            "-mpopcnt" in props["flags"]
            and "-msse4.1" in props["flags"]
            and "x86-64-modern" in targets
        ):
            res = "x86-64-modern"
        elif "-mssse3" in props["flags"] and "x86-64-ssse3" in targets:
            res = "x86-64-ssse3"
        elif (
            "-mpopcnt" in props["flags"]
            and "-msse3" in props["flags"]
            and "x86-64-sse3-popcnt" in targets
        ):
            res = "x86-64-sse3-popcnt"
        else:
            res = "x86-64"
    else:
        if (
            "-mpopcnt" in props["flags"]
            and "-msse4.1" in props["flags"]
            and "x86-32-sse41-popcnt" in targets
        ):
            res = "x86-32-sse41-popcnt"
        elif "-msse2" in props["flags"] and "x86-32-sse2" in targets:
            res = "x86-32-sse2"
        else:
            res = "x86-32"

    print("Available Makefile architecture targets: ", targets)
    print("Available g++/cpu properties: ", props)
    print("Determined the best architecture to be: ", res)

    return "ARCH=" + res


def setup_engine(destination, worker_dir, sha, repo_url, concurrency):
    if os.path.exists(destination):
        os.remove(destination)
    """Download and build sources in a temporary directory then move exe to destination"""
    tmp_dir = tempfile.mkdtemp()
    os.chdir(tmp_dir)

    with open("sf.gz", "wb+") as f:
        f.write(
            requests.get(
                github_api(repo_url) + "/zipball/" + sha, timeout=HTTP_TIMEOUT
            ).content
        )
    zip_file = ZipFile("sf.gz")
    zip_file.extractall()
    zip_file.close()

    for name in zip_file.namelist():
        if name.endswith("/src/"):
            src_dir = name
    os.chdir(src_dir)

    arch_string = find_arch_string()

    subprocess.check_call(
        MAKE_CMD + arch_string + " -j {}".format(concurrency) + " profile-build",
        shell=True,
    )
    try:  # try/pass needed for backwards compatibility with older stockfish, where 'make strip' fails under mingw.
        subprocess.check_call(
            MAKE_CMD + arch_string + " -j {}".format(concurrency) + " strip", shell=True
        )
    except:
        pass

    shutil.move("stockfish" + EXE_SUFFIX, destination)
    os.chdir(worker_dir)
    shutil.rmtree(tmp_dir)


def kill_process(p):
    try:
        if IS_WINDOWS:
            # Kill doesn't kill subprocesses on Windows
            subprocess.call(["taskkill", "/F", "/T", "/PID", str(p.pid)])
        else:
            p.kill()
    except:
        print(
            "Note: "
            + str(sys.exc_info()[0])
            + " killing the process pid: "
            + str(p.pid)
            + ", possibly already terminated"
        )
    finally:
        p.wait()
        p.stdout.close()


def adjust_tc(tc, base_nps, concurrency):
    factor = 1000000.0 / base_nps
    if base_nps < 100000:
        sys.stderr.write(
            "This machine is too slow to run fishtest effectively - sorry!\n"
        )
        sys.exit(1)

    # Parse the time control in cutechess format
    chunks = tc.split("+")
    increment = 0.0
    if len(chunks) == 2:
        increment = float(chunks[1])

    chunks = chunks[0].split("/")
    num_moves = 0
    if len(chunks) == 2:
        num_moves = int(chunks[0])

    time_tc = chunks[-1]
    chunks = time_tc.split(":")
    if len(chunks) == 2:
        time_tc = float(chunks[0]) * 60 + float(chunks[1])
    else:
        time_tc = float(chunks[0])

    # Rebuild scaled_tc now
    scaled_tc = "{:.3f}".format(time_tc * factor)
    tc_limit = time_tc * factor * 3
    if increment > 0.0:
        scaled_tc += "+{:.3f}".format(increment * factor)
        tc_limit += increment * factor * 400
    if num_moves > 0:
        scaled_tc = "{}/{}".format(num_moves, scaled_tc)
        tc_limit *= 100.0 / num_moves

    print("CPU factor : {} - tc adjusted to {}".format(factor, scaled_tc))
    return scaled_tc, tc_limit


def enqueue_output(out, queue):
    for line in iter(out.readline, ""):
        queue.put(line)


def run_game(p, remote, result, spsa, spsa_tuning, tc_limit):
    global old_stats

    q = Queue()
    t = threading.Thread(target=enqueue_output, args=(p.stdout, q))
    t.daemon = True
    t.start()

    end_time = datetime.datetime.now() + datetime.timedelta(seconds=tc_limit)
    print("TC limit {} End time: {}".format(tc_limit, end_time))

    while datetime.datetime.now() < end_time:
        try:
            line = q.get_nowait()
        except Empty:
            if p.poll() is not None:
                break
            time.sleep(1)
            continue

        sys.stdout.write(line)
        sys.stdout.flush()

        # Have we reached the end of the match?  Then just exit
        if "Finished match" in line:
            print("Finished match cleanly")

        # Parse line like this:
        # Finished game 1 (stockfish vs base): 0-1 {White disconnects}
        if "disconnects" in line or "connection stalls" in line:
            result["stats"]["crashes"] += 1

        if "on time" in line:
            result["stats"]["time_losses"] += 1

        # Parse line like this:
        # Score of stockfish vs base: 0 - 0 - 1  [0.500] 1
        if "Score" in line:
            chunks = line.split(":")
            chunks = chunks[1].split()
            wld = [int(chunks[0]), int(chunks[2]), int(chunks[4])]
            result["stats"]["wins"] = wld[0] + old_stats["wins"]
            result["stats"]["losses"] = wld[1] + old_stats["losses"]
            result["stats"]["draws"] = wld[2] + old_stats["draws"]

            if spsa_tuning:
                spsa["wins"] = wld[0]
                spsa["losses"] = wld[1]
                spsa["draws"] = wld[2]

            update_succeeded = False
            for _ in range(5):
                try:
                    req = requests.post(
                        remote + "/api/update_task",
                        data=json.dumps(result),
                        headers={"Content-type": "application/json"},
                        timeout=HTTP_TIMEOUT,
                    ).json()
                except Exception as e:
                    sys.stderr.write("Exception from calling update_task:\n")
                    print(e)
                else:
                    if not req["task_alive"]:
                        # This task is no longer necessary
                        print("Server told us task is no longer needed")
                        return req
                    update_succeeded = True
                    break
                time.sleep(HTTP_TIMEOUT)

            if not update_succeeded:
                print("Too many failed update attempts")
                break

    now = datetime.datetime.now()
    if now >= end_time:
        print("{} is past end time {}".format(now, end_time))

    return {"task_alive": True}


def launch_cutechess(cmd, remote, result, spsa_tuning, games_to_play, tc_limit):
    spsa = {
        "w_params": [],
        "b_params": [],
        "num_games": games_to_play,
    }

    if spsa_tuning:
        # Request parameters for next game
        req = requests.post(
            remote + "/api/request_spsa",
            data=json.dumps(result),
            headers={"Content-type": "application/json"},
            timeout=HTTP_TIMEOUT,
        ).json()

        spsa["w_params"] = req["w_params"]
        spsa["b_params"] = req["b_params"]

        result["spsa"] = spsa

    # Run cutechess-cli binary
    idx = cmd.index("_spsa_")
    cmd = (
        cmd[:idx]
        + [
            "option.{}={}".format(x["name"], int(round(x["value"])))
            for x in spsa["w_params"]
        ]
        + cmd[idx + 1 :]
    )
    idx = cmd.index("_spsa_")
    cmd = (
        cmd[:idx]
        + [
            "option.{}={}".format(x["name"], int(round(x["value"])))
            for x in spsa["b_params"]
        ]
        + cmd[idx + 1 :]
    )

    print(cmd)
    p = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        universal_newlines=True,
        bufsize=1,
        close_fds=not IS_WINDOWS,
    )

    task_state = {"task_alive": False}
    try:
        task_state = run_game(p, remote, result, spsa, spsa_tuning, tc_limit)
    except Exception as e:
        print("Exception running games")
        print(e)
    finally:
        kill_process(p)
    return task_state


def run_games(worker_info, password, remote, run, task_id):
    task = run["tasks"][task_id]
    result = {
        "username": worker_info["username"],
        "password": password,
        "run_id": str(run["_id"]),
        "task_id": task_id,
        "stats": {"wins": 0, "losses": 0, "draws": 0, "crashes": 0, "time_losses": 0},
    }

    # Have we run any games on this task yet?
    global old_stats
    old_stats = task.get(
        "stats", {"wins": 0, "losses": 0, "draws": 0, "crashes": 0, "time_losses": 0}
    )
    result["stats"]["crashes"] = old_stats.get("crashes", 0)
    result["stats"]["time_losses"] = old_stats.get("time_losses", 0)
    games_remaining = task["num_games"] - (
        old_stats["wins"] + old_stats["losses"] + old_stats["draws"]
    )
    if games_remaining <= 0:
        raise Exception("No games remaining")

    book = run["args"]["book"]
    book_depth = run["args"]["book_depth"]
    new_options = run["args"]["new_options"]
    base_options = run["args"]["base_options"]
    threads = int(run["args"]["threads"])
    spsa_tuning = "spsa" in run["args"]
    repo_url = run["args"].get("tests_repo", FISHCOOKING_URL)
    games_concurrency = int(worker_info["concurrency"]) / threads

    # Format options according to cutechess syntax
    def parse_options(s):
        results = []
        chunks = s.split("=")
        if len(chunks) == 0:
            return results
        param = chunks[0]
        for c in chunks[1:]:
            val = c.split()
            results.append("option.{}={}".format(param, val[0]))
            param = " ".join(val[1:])
        return results

    new_options = parse_options(new_options)
    base_options = parse_options(base_options)

    # Setup testing directory if not already exsisting
    worker_dir = os.path.dirname(os.path.realpath(__file__))
    testing_dir = os.path.join(worker_dir, "testing")
    if not os.path.exists(testing_dir):
        os.makedirs(testing_dir)

    # clean up old engines (keeping the 25 most recent)
    engines = glob.glob(os.path.join(testing_dir, "stockfish_*" + EXE_SUFFIX))
    engines.sort(key=os.path.getmtime)
    if len(engines) > 25:
        for old_engine in engines[: len(engines) - 25]:
            os.remove(old_engine)

    # create new one
    sha_new = run["args"]["resolved_new"]
    sha_base = run["args"]["resolved_base"]
    new_engine_name = "stockfish_" + sha_new
    base_engine_name = "stockfish_" + sha_base

    new_engine = os.path.join(testing_dir, new_engine_name + EXE_SUFFIX)
    base_engine = os.path.join(testing_dir, base_engine_name + EXE_SUFFIX)
    cutechess = os.path.join(testing_dir, "cutechess-cli" + EXE_SUFFIX)

    # Build from sources new and base engines as needed
    if not os.path.exists(new_engine):
        setup_engine(
            new_engine, worker_dir, sha_new, repo_url, worker_info["concurrency"]
        )
    if not os.path.exists(base_engine):
        setup_engine(
            base_engine, worker_dir, sha_base, repo_url, worker_info["concurrency"]
        )

    os.chdir(testing_dir)

    # Download book if not already existing
    if not os.path.exists(os.path.join(testing_dir, book)):
        setup(book, testing_dir, url=BOOKS_URL, branch="master")

    # Download cutechess if not already existing
    if not os.path.exists(cutechess):
        if len(EXE_SUFFIX) > 0:
            zipball = "cutechess-cli-win.zip"
        else:
            zipball = "cutechess-cli-linux-{}.zip".format(platform.architecture()[0])
        setup(zipball, testing_dir)
        zip_file = ZipFile(zipball)
        zip_file.extractall()
        zip_file.close()
        os.remove(zipball)
        os.chmod(cutechess, os.stat(cutechess).st_mode | stat.S_IEXEC)

    if os.path.exists("results.pgn"):
        os.remove("results.pgn")

    # Verify signatures are correct
    base_nps = verify_signature(
        new_engine,
        run["args"]["new_signature"],
        remote,
        result,
        games_concurrency * threads,
    )
    verify_signature(
        base_engine,
        run["args"]["base_signature"],
        remote,
        result,
        games_concurrency * threads,
    )

    # Benchmark to adjust cpu scaling
    scaled_tc, tc_limit = adjust_tc(
        run["args"]["tc"], base_nps, int(worker_info["concurrency"])
    )
    result["nps"] = base_nps

    # Handle book or pgn file
    pgn_cmd = []
    book_cmd = []
    if book.endswith(".pgn") or book.endswith(".epd"):
        plies = 2 * int(book_depth)
        pgn_cmd = [
            "-openings",
            "file={}".format(book),
            "format={}".format(book[-3:]),
            "order=random",
            "plies={}".format(plies),
        ]
    else:
        book_cmd = ["book={}".format(book), "bookdepth={}".format(book_depth)]

    print("Running {} vs {}".format(run["args"]["new_tag"], run["args"]["base_tag"]))

    if spsa_tuning:
        games_to_play = games_concurrency * 2
        pgnout = []
    else:
        games_to_play = games_remaining
        pgnout = ["-pgnout", "results.pgn"]

    threads_cmd = []
    if not any("Threads" in s for s in new_options + base_options):
        threads_cmd = ["option.Threads={}".format(threads)]

    # If nodestime is being used, give engines extra grace time to
    # make time losses virtually impossible
    nodestime_cmd = []
    if any("nodestime" in s for s in new_options + base_options):
        nodestime_cmd = ["timemargin=10000"]

    while games_remaining > 0:
        # Run cutechess-cli binary
        cmd = (
            [
                cutechess,
                "-repeat",
                "-games",
                str(int(games_to_play)),
                "-tournament",
                "gauntlet",
            ]
            + pgnout
            + [
                "-srand",
                "{}".format(struct.unpack("<L", os.urandom(struct.calcsize("<L")))[0]),
            ]
            + [
                "-resign",
                "movecount=8",
                "score=800",
                "-draw",
                "movenumber=34",
                "movecount=8",
                "score=20",
                "-concurrency",
                str(int(games_concurrency)),
            ]
            + pgn_cmd
            + ["-variant", run["args"]["variant"]]
            + ["-engine", "name=stockfish", "cmd={}".format(new_engine_name)]
            + new_options
            + ["_spsa_"]
            + ["-engine", "name=base", "cmd={}".format(base_engine_name)]
            + base_options
            + ["_spsa_"]
            + ["-each", "proto=uci", "tc={}".format(scaled_tc)]
            + nodestime_cmd
            + threads_cmd
            + book_cmd
        )

        task_status = launch_cutechess(
            cmd,
            remote,
            result,
            spsa_tuning,
            games_to_play,
            tc_limit * games_to_play / min(games_to_play, games_concurrency),
        )
        if not task_status.get("task_alive", False):
            break

        old_stats = result["stats"].copy()
        games_remaining -= games_to_play
