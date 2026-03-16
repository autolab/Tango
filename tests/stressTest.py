import argparse
import subprocess
import time
import os
import sys

import tornado.web

import yaml

test_dir = ""
sub_num = 0
finished_tests = dict()
start_time = time.time()
expected_output = ""


def printProgressBar(
    iteration,
    total,
    prefix="",
    suffix="",
    decimals=1,
    length=100,
    fill="█",
    printEnd="\r",
):
    """
    Call in a loop to create terminal progress bar
    @params:
        iteration   - Required  : current iteration (Int)
        total       - Required  : total iterations (Int)
        prefix      - Optional  : prefix string (Str)
        suffix      - Optional  : suffix string (Str)
        decimals    - Optional  : positive number of decimals in percent complete (Int)
        length      - Optional  : character length of bar (Int)
        fill        - Optional  : bar fill character (Str)
        printEnd    - Optional  : end character (e.g. "\r", "\r\n") (Str)
    """
    percent = ("{0:." + str(decimals) + "f}").format(100 * (iteration / float(total)))
    filledLength = int(length * iteration // total)
    bar = fill * filledLength + "-" * (length - filledLength)
    print(f"\r{prefix} |{bar}| {percent}% {suffix}", end=printEnd)
    # Print New Line on Complete
    if iteration == total:
        print()


def run_stress_test(
    num_submissions,
    submission_delay,
    autograder_image,
    output_file,
    tango_port,
    cli_path,
    job_name,
    job_path,
    instance_type,
    timeout,
    ec2,
):
    printProgressBar(
        0, num_submissions, prefix="Jobs Added:", suffix="Complete", length=50
    )
    with open(output_file, "a") as f:
        f.write(f"Stress testing with {num_submissions} submissions\n")

        for i in range(1, num_submissions + 1):
            command = [
                "python3",
                cli_path,
                "-P",
                str(tango_port),
                "-k",
                "test",
                "-l",
                job_name,
                "--runJob",
                job_path,
                "--image",
                autograder_image,
                "--instanceType",
                instance_type,
                "--timeout",
                str(timeout),
                "--callbackURL",
                ("http://localhost:8888/autograde_done?id=%d" % (i)),
            ]
            if ec2:
                command += ["--ec2"]
            subprocess.run(command, stdout=f, stderr=f)
            f.write(f"Submission {i} completed\n")
            printProgressBar(
                i, num_submissions, prefix="Jobs Added:", suffix="Complete", length=50
            )
            if submission_delay > 0:
                time.sleep(submission_delay)
        print()


class AutogradeDoneHandler(tornado.web.RequestHandler):
    def post(self):
        global finished_tests
        global test_dir
        global sub_num
        global start_time
        id = self.get_query_argument("id")
        fileBody = self.request.files["file"][0]["body"].decode()
        scoreJson = fileBody.split("\n")[-2]
        with open(os.path.join(test_dir, "output", "output%s.txt" % id), "w") as f:
            f.write(fileBody)
        finished_tests[str(id)] = scoreJson
        printProgressBar(
            len(finished_tests),
            sub_num,
            prefix="Tests Done:",
            suffix="Complete",
            length=50,
        )
        self.write("ok")
        self.flush()

    def on_finish(self):
        global finished_tests, sub_num, shutdown_event
        if len(finished_tests) == sub_num:
            print("\nAll tests completed. Generating summary...")
            create_summary()
            print("Test Summary in summary.txt")
            print("\nShutting down server...")
            tornado.ioloop.IOLoop.current().stop()


def create_summary():
    success = []
    failed = []
    for i in range(1, sub_num + 1):
        if expected_output == finished_tests[str(i)]:
            success.append(i)
        else:
            failed.append(i)
    with open(os.path.join(test_dir, "summary.txt"), "w") as f:
        f.write("Total Time: %d seconds\n" % (time.time() - start_time))
        f.write("Total Succeeded: %d / %d\n" % (len(success), sub_num))
        f.write("Total Failed: %d / %d\n" % (len(failed), sub_num))
        f.write("\n===========================================================\n")
        f.write("The expected value is:\n")
        f.write(expected_output)
        f.write("\n\n===========================================================\n")
        f.write("Failed Cases:\n")
        for i in range(0, len(failed)):
            f.write("Test Case #%d: %s\n" % (failed[i], finished_tests[str(failed[i])]))


def make_app():
    return tornado.web.Application(
        [
            (r"/autograde_done", AutogradeDoneHandler),
        ]
    )


def notifyServer():
    global shutdown_event
    app = make_app()
    app.listen(8888)
    printProgressBar(0, sub_num, prefix="Tests Done:", suffix="Complete", length=50)
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Stress test script for Tango")
    parser.add_argument(
        "--test_dir", type=str, required=True, help="Directory to run the test in"
    )

    args = parser.parse_args()

    dirname = os.path.basename(args.test_dir)

    test_dir = args.test_dir

    with open(os.path.join(args.test_dir, dirname + ".yaml"), "r") as f:
        data = yaml.load(f, Loader=yaml.SafeLoader)

    with open(os.path.join(args.test_dir, data["expected_output"]), "r") as f:
        expected_output = f.read()

    sub_num = data["num_submissions"]
    finished_tests = dict()
    start_time = time.time()

    subprocess.run("rm -rf %s/output" % args.test_dir, shell=True)
    subprocess.run("mkdir %s/output" % args.test_dir, shell=True)

    print()

    run_stress_test(
        data["num_submissions"],
        data["submission_delay"],
        data["autograder_image"],
        os.path.join(args.test_dir, data["output_file"]),
        data["tango_port"],
        data["cli_path"],
        dirname,
        os.path.join(args.test_dir, "input"),
        data["instance_type"],
        data["timeout"],
        data["ec2"],
    )

    notifyServer()
