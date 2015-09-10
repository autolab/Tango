![Welcome to Autolab](https://github.com/autolab/Autolab/blob/master/public/images/autolab_logo.png)

Tango [![Circle CI](https://circleci.com/gh/autolab/Tango.svg?style=svg)](https://circleci.com/gh/autolab/Tango)
======

Tango is a standalone RESTful Web service that runs and manages jobs. A job is a set of files that must satisfy the following constraints:

1. There must be exactly one `Makefile` that runs the job.
2. The output for the job should be printed to stdout. 

Example jobs are provided for the user to peruse in `clients/`. Tango has a [REST API](https://github.com/autolab/Tango/wiki/Tango-REST-API) which is used for job submission.

Upon receiving a job, Tango will copy all of the job's input files into a VM, run `make`, and copy the resulting output back to the host machine. Tango jobs are run in pre-configured VMs. Support for various Virtual Machine Management Systems (VMMSs) like KVM, Docker, or Amazon EC2 can be added by implementing a high level VMMS API that Tango provides.

A brief overview of the Tango respository:

* `tangod.py` - Main tango server
* `jobQueue.py` - Manages the job queue
* `jobManager.py` - Assigns jobs to free VMs
* `worker.py` - Shepherds a job through its execution
* `preallocator.py` - Manages pools of VMs
* `vmms/` - VMMS library implementations
* `restful-tango/` - HTTP server layer on the main Tango

Tango was developed as a distributed grading system for [Autolab](https://github.com/autolab/Autolab) at Carnegie Mellon University and has been extensively used for autograding programming assignments in CMU courses. 

## Using Tango

Please feel free to use Tango at your school/organization. If you run into any problems with the steps below, you can reach the core developers at `autolab-dev@andrew.cmu.edu` and we would be happy to help.

1. [Follow the steps to set up Tango](https://github.com/autolab/Tango/wiki/Set-up-Tango).
2. [Read the documentation for the REST API](https://github.com/autolab/Tango/wiki/Tango-REST-API).
3. Read the documentation for the VMMS API - coming soon.
4. [Test whether Tango is set up properly and can process jobs](https://github.com/autolab/Tango/wiki/Testing-Tango).

## Contributing to Tango

1. [Fork the Tango repository](https://github.com/autolab/Tango).
2. Create a local clone of the forked repo.
3. Make a branch for your feature and start committing changes.
3. Create a pull request (PR).
4. Address any comments by updating the PR and wait for it to be accepted.
5. Once your PR is accepted, a reviewer will ask you to squash the commits on your branch into one well-worded commit.
6. Squash your commits into one and push to your branch on your forked repo. 
7. A reviewer will fetch from your repo, rebase your commit, and push to Tango.
 
Please see [the git linear development guide](https://github.com/edx/edx-platform/wiki/How-to-Rebase-a-Pull-Request) for a more in-depth explanation of the version control model that we use.  

## License

Tango is released under the [Apache License 2.0](http://opensource.org/licenses/Apache-2.0). 
