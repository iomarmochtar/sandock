from typing import List
from ..shared import KV, list_remove_element
from ..sandbox import SandboxExec, CONTAINER_STATE_RUNNING


class AppleContainerExec(SandboxExec):
    @property
    def docker_bin(self) -> str:
        return "container"

    def run_container_cmd(self) -> List[str]:
        """
        some parameters are run supported
        """
        cmds = super().run_container_cmd()
        return list_remove_element(source=cmds, elem="--hostname")

    def inspect_container_cmd(self) -> str:
        return f"{self.docker_bin} inspect {self.container_name}"

    def _check_running_container(self, container_info: List[KV]) -> bool:
        return container_info[0].get("status") == CONTAINER_STATE_RUNNING

    def container_start_cmd(self) -> str:
        return f"{self.docker_bin} start {self.container_name}"
