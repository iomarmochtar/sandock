class SandboxBaseException(Exception):
    pass


class SandboxExecConfig(SandboxBaseException):
    """
    errors related to configuration
    """


class SandboxExecution(SandboxBaseException):
    pass


class SandboxVolumeExec(SandboxBaseException):
    pass


class SandboxVolumeNotFound(SandboxBaseException):
    pass
