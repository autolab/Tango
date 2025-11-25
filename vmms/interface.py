from typing import Protocol, Optional, Literal, List
from tangoObjects import TangoMachine
from abc import abstractmethod


class VMMSInterface(Protocol):
    @abstractmethod
    def initializeVM(self, vm: TangoMachine) -> Literal[0, -1]:
        ...

    @abstractmethod
    def waitVM(self, vm: TangoMachine, max_secs: int) -> Literal[0, -1]:
        ...

    @abstractmethod
    def copyIn(self, vm: TangoMachine, inputFiles: List[str], job_id: Optional[int] = None) -> Literal[0, -1]:
        ...

    @abstractmethod
    def runJob(self, vm: TangoMachine, runTimeout: int, maxOutputFileSize: int, disableNetwork: bool) -> int: # -1 to infinity
        ...

    @abstractmethod
    def copyOut(self, vm: TangoMachine, destFile: str) -> Literal[0, -1]:
        ...

    @abstractmethod
    def destroyVM(self, vm: TangoMachine) -> Literal[0, -1]:
        ...
    
    @abstractmethod
    def safeDestroyVM(self, vm: TangoMachine) -> Literal[0, -1]:
        ...

    @abstractmethod
    def getVMs(self) -> List[TangoMachine]:
        ...

    @abstractmethod
    def existsVM(self, vm: TangoMachine) -> bool:
        ...

