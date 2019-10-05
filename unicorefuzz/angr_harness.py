#!/usr/bin/env python3

import argparse
from typing import Optional, Dict, Tuple, Callable

import angr
import claripy

from unicorefuzz.harness import Harness


class PageForwardingExplorer(angr.ExplorationTechnique):
    """
    Angr explorer forwarding unmapped pages once they are hit
    """

    def __init__(self, page_fetcher: Callable[[int], Tuple[int, bytes]]) -> None:
        """
        :param page_fetcher: A function that takes an addr and returns a Tuple of (base_addr, content) of this page.
        """
        super().__init__()
        self.page_fetcher = page_fetcher  # type: Callable[[int], Tuple[int, bytes]]

    def step(self, simgr: angr.SimulationManager, **kwargs) -> angr.SimulationManager:
        super().step(simgr, **kwargs)
        print(simgr)
        new_active = []
        for r in simgr.errored:
            s = r.state
            if isinstance(
                r.error, angr.errors.SimEngineError
            ) and "No bytes in memory" in repr(r.error):
                addr = s.solver.eval_one(s.regs.rip)
            elif isinstance(r.error, angr.errors.SimSegfaultException):
                addr = r.error.addr
            else:
                r.reraise()
                # explicitly raise, just to make pycharm happy
                raise r.error.with_traceback(r.traceback)

            print("mapping addr: 0x{:016x}".format(addr))
            pageaddr, pagecontent = self.page_fetcher(addr)
            try:
                s.memory.map_region(pageaddr, len(pagecontent), 7)
            except Exception as ex:
                print("Could not map: {}".format(ex))

            s.memory.store(pageaddr, pagecontent)
            new_active.append(s)

        simgr.drop(stash="errored")  # Todo: only remove fixed ones.
        simgr.active.extend(new_active)
        return simgr


class AngrHarness(Harness):
    def angr_load_registers(self, ucf, state):
        """
        Load registers to angr
        """
        for reg in state.arch.register_names.values():
            try:
                state.registers.store(reg, ucf.fetch_reg(reg))
            except Exception as ex:
                print("Failed to retrieve register {}: {}".format(reg, ex))

    def __init__(self, config) -> None:
        super().__init__(config)
        self.fetched_regs = None  # type: Optional[Dict[str, int]]

    def get_angry(self):
        self.uc


def main(input_file):
    rip = utils.fetch_register("rip")
    pageaddr, pagecontent = utils.fetch_page_blocking(rip)
    pagepath = utils.path_for_page(pageaddr)

    p = angr.Project(
        pagepath,
        load_options={
            "main_opts": {"backend": "blob", "base_addr": pageaddr, "arch": "x86_64"}
        },
    )

    state = p.factory.blank_state(
        add_options=angr.options.unicorn | {angr.options.REPLACEMENT_SOLVER}
    )
    utils.angr_load_registers(state)

    # s.solver.eval_one(s.regs.rdi)
    rdi = utils.fetch_register("rdi")
    pageaddr, content = utils.fetch_page_blocking(rdi)

    state.memory.map_region(pageaddr, len(content), 7)
    state.memory.store(pageaddr, content)

    input_file = open(input_file, "rb")  # load afl's input

    input = input_file.read()
    input_file.close()

    input_symbolic = claripy.BVS("input", len(input) * 8)

    state.preconstrainer.preconstrain(input, input_symbolic)
    state.regs.rsi = len(input)

    state.memory.store(rdi, input_symbolic)

    simgr = p.factory.simulation_manager(state)
    simgr.use_technique(PageForwardingExplorer())
    simgr.use_technique(angr.exploration_techniques.DFS())
    while simgr.active:
        print(simgr)
        simgr.step()

    return


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Angr-Harness for unicorefuzz")
    parser.add_argument(
        "input_file",
        type=str,
        help="Path to the file containing the mutated input to load",
    )
    args = parser.parse_args()

    main(args.input_file)
