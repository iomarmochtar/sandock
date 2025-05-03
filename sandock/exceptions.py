class SandboxBaseException(Exception):
    pass


class SandboxExecConfig(SandboxBaseException):
    """
    errors related to configuration
    """


class SandboxExecution(SandboxBaseException):
    pass
