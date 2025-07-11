#!/usr/bin/python
from __future__ import print_function

import json
import multiprocessing
import os
import platform
import signal
import sys
import time
import traceback
import uuid
from optparse import OptionParser

import requests
from games import run_games
from updater import update

try:
    from ConfigParser import SafeConfigParser

    config = SafeConfigParser()
except ImportError:
    from configparser import ConfigParser  # Python3

    config = ConfigParser()

WORKER_VERSION = 72
ALIVE = True

HTTP_TIMEOUT = 30.0


def setup_config_file(config_file):
    """ Config file setup, adds defaults if not existing """
    config.read(config_file)

    defaults = [
        ("login", "username", ""),
        ("login", "password", ""),
        ("parameters", "host", "www.variantfishtest.org"),
        ("parameters", "port", "6543"),
        ("parameters", "concurrency", "3"),
    ]

    for v in defaults:
        if not config.has_section(v[0]):
            config.add_section(v[0])
        if not config.has_option(v[0], v[1]):
            config.set(*v)
            with open(config_file, "w") as f:
                config.write(f)

    return config


def on_sigint(signal, frame):
    global ALIVE
    ALIVE = False
    raise Exception("Terminated by signal")


def worker(worker_info, password, remote):
    global ALIVE

    payload = {
        "worker_info": worker_info,
        "password": password,
    }

    try:
        req = requests.post(
            remote + "/api/request_version",
            data=json.dumps(payload),
            headers={"Content-type": "application/json"},
            timeout=HTTP_TIMEOUT,
        )
        req = json.loads(req.text)

        if "version" not in req:
            print("Incorrect username/password")
            time.sleep(5)
            sys.exit(1)

        if req["version"] > WORKER_VERSION:
            print("Updating worker version to {}".format(req["version"]))
            update()

        req = requests.post(
            remote + "/api/request_task",
            data=json.dumps(payload),
            headers={"Content-type": "application/json"},
            timeout=HTTP_TIMEOUT,
        )
        req = json.loads(req.text)
    except:
        sys.stderr.write("Exception accessing host:\n")
        traceback.print_exc()
        time.sleep(10)
        return

    if "error" in req:
        raise Exception("Error from remote: {}".format(req["error"]))

    # No tasks ready for us yet, just wait...
    if "task_waiting" in req:
        print("No tasks available at this time, waiting...")
        time.sleep(10)
        return

    success = True
    run, task_id = req["run"], req["task_id"]
    try:
        run_games(worker_info, password, remote, run, task_id)
    except:
        sys.stderr.write("\nException running games:\n")
        traceback.print_exc()
        success = False
    finally:
        payload = {
            "username": worker_info["username"],
            "password": password,
            "run_id": str(run["_id"]),
            "task_id": task_id,
        }
        try:
            requests.post(
                remote + "/api/failed_task",
                data=json.dumps(payload),
                headers={"Content-type": "application/json"},
                timeout=HTTP_TIMEOUT,
            )
        except:
            pass
        sys.stderr.write("Task exited\n")

    return success


def main():
    signal.signal(signal.SIGINT, on_sigint)
    signal.signal(signal.SIGTERM, on_sigint)

    worker_dir = os.path.dirname(os.path.realpath(__file__))
    config_file = os.path.join(worker_dir, "fishtest.cfg")
    config = setup_config_file(config_file)
    parser = OptionParser()
    parser.add_option(
        "-n", "--host", dest="host", default=config.get("parameters", "host")
    )
    parser.add_option(
        "-p", "--port", dest="port", default=config.get("parameters", "port")
    )
    parser.add_option(
        "-c",
        "--concurrency",
        dest="concurrency",
        default=config.get("parameters", "concurrency"),
    )
    (options, args) = parser.parse_args()

    if len(args) != 2:
        # Try to read parameters from the the config file
        username = config.get("login", "username")
        password = config.get("login", "password", raw=True)
        if len(username) != 0 and len(password) != 0:
            args.extend([username, password])
        else:
            sys.stderr.write("{} [username] [password]\n".format(sys.argv[0]))
            sys.exit(1)

    # Write command line parameters to the config file
    config.set("login", "username", args[0])
    config.set("login", "password", args[1])
    config.set("parameters", "host", options.host)
    config.set("parameters", "port", options.port)
    config.set("parameters", "concurrency", options.concurrency)
    with open(config_file, "w") as f:
        config.write(f)

    remote = "http://{}:{}".format(options.host, options.port)
    print("Worker version {} connecting to {}".format(WORKER_VERSION, remote))

    try:
        cpu_count = min(int(options.concurrency), multiprocessing.cpu_count() - 1)
    except:
        cpu_count = int(options.concurrency)

    if cpu_count <= 0:
        sys.stderr.write("Not enough CPUs to run fishtest (it requires at least two)\n")
        sys.exit(1)

    uname = platform.uname()
    worker_info = {
        "uname": uname[0] + " " + uname[2],
        "architecture": platform.architecture(),
        "concurrency": cpu_count,
        "username": args[0],
        "version": "{}:{}.{}.{}".format(
            WORKER_VERSION,
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        ),
        "unique_key": str(uuid.uuid4()),
    }

    success = True
    global ALIVE
    while ALIVE:
        if not success:
            time.sleep(300)
        success = worker(worker_info, args[1], remote)


if __name__ == "__main__":
    main()
