#
# preallocator.py - maintains a pool of active virtual machines
#
import threading, logging, time, copy, os

from tangoObjects import TangoDictionary, TangoQueue, TangoIntValue
from config import Config

#
# Preallocator - This class maintains a pool of active VMs for future
# job requests.  The pool is stored in dictionary called
# "machines". This structure keys off the name of the TangoMachine
# (.name).  The values of this dictionary are two-element arrays:
# Element 0 is the list of the IDs of the current VMs in this pool.
# Element 1 is a queue of the VMs in this pool that are available to
# be assigned to workers.
#


class Preallocator:

    def __init__(self, vmms):
        self.machines = TangoDictionary("machines")
        self.lock = threading.Lock()
        self.nextID = TangoIntValue("nextID", 1000)
        self.vmms = vmms
        self.log = logging.getLogger("Preallocator-" + str(os.getpid()))

    def poolSize(self, vmName):
        """ poolSize - returns the size of the vmName pool, for external callers
        """
        if vmName not in self.machines.keys():
            return 0
        else:
            return len(self.machines.get(vmName)[0])

    def freePoolSize(self, vmName):
        """ freePoolSize - returns the size of the vmName free pool, for external callers
        """
        if vmName in self.machines.keys():
            return self.machines.get(vmName)[1].qsize()
        else:
            return 0

    def incrementPoolSize(self, vm, delta):
        """
        Called by jobQueue to create the pool and allcoate given number of vms
        """

        self.lock.acquire()
        if vm.name not in self.machines.keys():
            self.machines.set(vm.name, [[], TangoQueue(vm.name)])
            # see comments in jobManager.py for the same call
            self.machines.get(vm.name)[1].make_empty()
            self.log.debug("Creating empty pool of %s instances" % (vm.name))
        self.lock.release()

        self.log.debug("incrementPoolSize: add %d new %s instances" % (delta, vm.name))
        threading.Thread(target=self.__create(vm, delta)).start()

    def update(self, vm, num):
        """ update - Updates the number of machines of a certain type
        to be preallocated.

        This function is called via the TangoServer HTTP interface.
        It will validate the request,update the machine list, and 
        then spawn child threads to do the creation and destruction 
        of machines as necessary.
        """
        self.lock.acquire()
        if vm.name not in self.machines.keys():
            self.machines.set(vm.name, [[], TangoQueue(vm.name)])
            # see comments in jobManager.py for the same call
            self.machines.get(vm.name)[1].make_empty()
            self.log.debug("Creating empty pool of %s instances" % (vm.name))
        self.lock.release()

        delta = num - len(self.machines.get(vm.name)[0])
        if delta > 0:
            # We need more self.machines, spin them up.
            self.log.debug(
                "update: Creating %d new %s instances" % (delta, vm.name))
            threading.Thread(target=self.__create(vm, delta)).start()

        elif delta < 0:
            # We have too many self.machines, remove them from the pool
            self.log.debug(
                "update: Destroying %d preallocated %s instances" %
                (-delta, vm.name))
            for i in range(-1 * delta):
                threading.Thread(target=self.__destroy(vm)).start()

        # If delta == 0 then we are the perfect number!

    def allocVM(self, vmName):
        """ allocVM - Allocate a VM from the free list
        """
        vm = None
        if vmName in self.machines.keys():
            self.lock.acquire()

        if not self.machines.get(vmName)[1].empty():
            vm = self.machines.get(vmName)[1].get_nowait()

        self.lock.release()

        # If we're not reusing instances, then crank up a replacement
        if vm and not Config.REUSE_VMS:
            threading.Thread(target=self.__create(vm, 1)).start()

        return vm

    def addToFreePool(self, vm):
        """ addToFreePool - Returns a VM instance to the free list
        """

        self.lock.acquire()
        machine = self.machines.get(vm.name)
        self.log.info("addToFreePool: add %s to free pool" % vm.id)
        machine[1].put(vm)
        self.machines.set(vm.name, machine)
        self.lock.release()

    def freeVM(self, vm):
        """ freeVM - Returns a VM instance to the free list
        """
        # Sanity check: Return a VM to the free list only if it is
        # still a member of the pool.
        not_found = False
        should_destroy = False
        self.lock.acquire()
        if vm and vm.id in self.machines.get(vm.name)[0]:
            if (hasattr(Config, 'POOL_SIZE_LOW_WATER_MARK') and
                Config.POOL_SIZE_LOW_WATER_MARK >= 0 and
                vm.name in self.machines.keys() and
                self.freePoolSize(vm.name) >= Config.POOL_SIZE_LOW_WATER_MARK):
                self.log.info("freeVM: over low water mark. will destroy %s" % vm.id)
                should_destroy = True
            else:
                machine = self.machines.get(vm.name)
                self.log.info("freeVM: return %s to free pool" % vm.id)
                machine[1].put(vm)
                self.machines.set(vm.name, machine)
        else:
            self.log.info("freeVM: not found in pool %s.  will destroy %s" % (vm.name, vm.id))
            not_found = True
        self.lock.release()

        # The VM is no longer in the pool.
        if not_found or should_destroy:
            self.log.info("freeVM: will destroy %s" % vm.id)
            vmms = self.vmms[vm.vmms]
            self.removeVM(vm)
            vmms.safeDestroyVM(vm)

    def addVM(self, vm):
        """ addVM - add a particular VM instance to the pool
        """
        self.lock.acquire()
        machine = self.machines.get(vm.name)
        machine[0].append(vm.id)
        self.log.info("addVM: add %s" % vm.id)
        self.machines.set(vm.name, machine)
        self.lock.release()

    # Note: This function is called from removeVM() to handle the case when a vm
    # is in free pool.  In theory this should never happen but we want to ensure
    # that.  To solve the problem cleanly, preallocator should provide ONE primitive
    # to add/remove a vm from both total and free pools, instead of two disjoint ones.
    def removeFromFreePool(self, vm):
        self.lock.acquire()
        size = self.machines.get(vm.name)[1].qsize()
        self.log.info("removeFromFreePool: %s in pool %s" % (vm.id, vm.name))
        for i in range(size):  # go through free pool
            freeVM = self.machines.get(vm.name)[1].get_nowait()
            # put it back into free pool, if not our vm
            if vm.id != freeVM.id:
                self.machines.get(vm.name)[1].put(freeVM)
            else:
                self.log.info("removeFromFreePool: found %s in pool %s" % (vm.id, vm.name))
                # don't put this particular vm back to free pool, that is removal
        self.lock.release()

    # return True if the vm is in the pool (and removed)
    def removeVM(self, vm, mustFind=True):
        """ removeVM - remove a particular VM instance from the pool
        """
        self.lock.acquire()
        machine = self.machines.get(vm.name)
        if not machine or vm.id not in machine[0]:
            if mustFind:
                self.log.error("removeVM: %s NOT found in pool" % vm.name)
            else:
                self.log.info("removeVM: %s NOT found in pool. This is OK" % vm.name)
            self.lock.release()
            return False

        self.log.info("removeVM: %s" % vm.id)
        machine[0].remove(vm.id)
        self.machines.set(vm.name, machine)
        self.lock.release()

        self.removeFromFreePool(vm)  # also remove from free pool, just in case
        return True

    def _getNextID(self):
        """ _getNextID - returns next ID to be used for a preallocated
        VM.  Preallocated VM's have 4-digit ID numbers between 1000
        and 9999.
        """
        self.lock.acquire()
        id = self.nextID.get()

        self.nextID.increment()

        if self.nextID.get() > 9999:
            self.nextID.set(1000)

        self.lock.release()
        return id

    def __create(self, vm, cnt):
        """ __create - Creates count VMs and adds them to the pool

        This function should always be called in a thread since it
        might take a long time to complete.
        """

        vmms = self.vmms[vm.vmms]
        self.log.debug("__create: Using VMMS %s " % (Config.VMMS_NAME))
        for i in range(cnt):
            newVM = copy.deepcopy(vm)
            newVM.id = self._getNextID()
            self.log.debug("__create|calling initializeVM")
            ret = vmms.initializeVM(newVM)
            if not ret:    # ret is None when fails
                self.log.debug("__create|failed initializeVM")
                continue
            self.log.debug("__create|done with initializeVM")
            time.sleep(Config.CREATEVM_SECS)

            self.addVM(newVM)
            self.addToFreePool(newVM)
            self.log.debug("__create: Added vm %s to pool %s " %
                           (newVM.id, newVM.name))

    def __destroy(self, vm):
        """ __destroy - Removes a VM from the pool

        If the user asks for fewer preallocated VMs, then we will
        remove some excess ones. This function should be called in a
        thread context. Notice that we can only remove a free vm, so
        it's possible we might not be able to satisfy the request if
        the free list is empty.
        """
        self.lock.acquire()
        dieVM = self.machines.get(vm.name)[1].get_nowait()
        self.lock.release()

        if dieVM:
            self.log.info("__destroy: %s" % dieVM.id)
            self.removeVM(dieVM)
            vmms = self.vmms[vm.vmms]
            vmms.safeDestroyVM(dieVM)

    def createVM(self, vm):
        """ createVM - Called in non-thread context to create a single
        VM and add it to the pool
        """

        vmms = self.vmms[vm.vmms]
        newVM = copy.deepcopy(vm)
        newVM.id = self._getNextID()

        self.log.info("createVM|calling initializeVM")
        ret = vmms.initializeVM(newVM)
        if not ret:
            self.log.debug("createVM|failed initializeVM")
            return
        self.log.info("createVM|done with initializeVM %s" % newVM.id)

        self.addVM(newVM)
        self.addToFreePool(newVM)
        self.log.debug("createVM: Added vm %s to pool %s" %
                       (newVM.id, newVM.name))

    def destroyVM(self, vmName, id):
        """ destroyVM - Called by the delVM API function to remove and
        destroy a particular VM instance from a pool. We only allow
        this function when the system is queiscent (pool size == free
        size)
        """
        if vmName not in self.machines.keys():
            return -1

        dieVM = None
        self.lock.acquire()
        size = self.machines.get(vmName)[1].qsize()
        self.log.info("destroyVM: free:total pool %d:%d" % (size, len(self.machines.get(vmName)[0])))
        if (size == len(self.machines.get(vmName)[0])):
            for i in range(size):
                vm = self.machines.get(vmName)[1].get_nowait()
                if vm.id != id:
                    self.log.info("destroyVM: put to free pool id:vm.id %s:%s" % (id, vm.id))
                    self.machines.get(vmName)[1].put(vm)
                else:
                    self.log.info("destroyVM: will call removeVM %s" % id)
                    dieVM = vm
        self.lock.release()

        if dieVM:
            self.removeVM(dieVM)
            vmms = self.vmms[vm.vmms]
            vmms.safeDestroyVM(dieVM)
            return 0
        else:
            return -1

    def getAllPools(self):
        result = {}
        for vmName in self.machines.keys():
            result[vmName] = self.getPool(vmName)
        return result

    def getPool(self, vmName):
        """ getPool - returns the members of a pool and its free list
        """
        result = {}
        if vmName not in self.machines.keys():
            return result

        result["total"] = []
        result["free"] = []
        free_list = []
        self.lock.acquire()
        size = self.machines.get(vmName)[1].qsize()
        for i in range(size):
            vm = self.machines.get(vmName)[1].get_nowait()
            free_list.append(vm.id)
            machine = self.machines.get(vmName)
            machine[1].put(vm)
            self.machines.set(vmName, machine)
        self.lock.release()

        result["total"] = self.machines.get(vmName)[0]
        result["free"] = free_list
        self.log.info("getPool: free pool %s" % ', '.join(str(x) for x in result["free"]))
        self.log.info("getPool: total pool %s" % ', '.join(str(x) for x in result["total"]))

        return result
