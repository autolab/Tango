![Welcome to Autolab](https://github.com/autolab/Autolab/blob/master/public/images/autolab_logo.png)

Tango
======

Tango is a standalone, RESTful external job service that is primarily used by [Autolab](https://github.com/autolab/Autolab). This is the main repository that includes the application layer of the project.

Tango allows submission of jobs that are to be run in pre-configured VMs. Tango also supports different Virtual Machine Management (VMM) systems by providing a high level VMM API. Users can implement the high level VMM API for a hypervisor or VMM of your choice such as KVM, Xen, Docker or EC2.

Tango was started as part of the Autolab project at Carnegie Mellon University and has been extensively used for running grading jobs.

## Getting Started

The easiest way to get started with Tango is by installing it on a vanilla EC2 Ubuntu instance. The detailed instructions can be found [here](https://github.com/autolab/Tango/wiki/Setting-up-Tango-and-VMs-on-Amazon-EC2).

Tango has a REST API which can be used for job submission and other administrative tasks. The documentation of the API can be found [here](https://github.com/autolab/Tango/wiki/Tango-REST-API)

In order to run Tango locally, the VMM API needs to be implemented such that jobs run locally. This is currently work in progress.

A brief overview of the Tango respository:

* tangod.py - Main tango program
* jobQueue.py - Manages the job queue
* preallocator.py - Manages a pool of preallocated VMs
* worker.py - Shepherds a job through its execution
* vmms - VMM system library implementations
* restful-tango - HTTP server layer on the main tango

## Testing

To test whether Tango is running and accepting jobs, a tango command-line client is included in `clients/` along with sample jobs.

## Contributing

Contributing to Tango is greatly encouraged! Future issues and features will be posted on Github Issues. Also look at [Contributing to Autolab Guide](https://github.com/autolab/Autolab) for guidelines on how to proceed. [Join us!](http://contributors.autolabproject.org)

## License

Autolab is released under the [Apache License 2.0](http://opensource.org/licenses/Apache-2.0). 

## Using Tango

Please feel free to use Tango at your school/organization. If you run into any problems, you can reach the core developers at `autolab-dev@andrew.cmu.edu` and we would be happy to help. On a case by case basis, we also provide servers for free. (Especially if you are an NGO or small high-school classroom)
