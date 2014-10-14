# -*- coding: utf-8 -*-

import numpy as np
import pyopencl as cl

from pyfr.backends.base import ComputeKernel, MPIKernel
from pyfr.backends.opencl.provider import OpenCLKernelProvider
from pyfr.backends.opencl.types import OpenCLXchgView


class OpenCLPackingKernels(OpenCLKernelProvider):
    def _sendrecv(self, mv, mpipreqfn, pid, tag):
        # If we are an exchange view then extract the exchange matrix
        xchgmat = mv.xchgmat if isinstance(mv, OpenCLXchgView) else mv

        # Create a persistent MPI request to send/recv the pack
        preq = mpipreqfn(xchgmat.hdata, pid, tag)

        class SendRecvPackKernel(MPIKernel):
            def run(self, queue):
                # Start the request and append us to the list of requests
                preq.Start()
                queue.mpi_reqs.append(preq)

        return SendRecvPackKernel()

    def pack(self, mv):
        # An exchange view is simply a regular view plus an exchange matrix
        m, v = mv.xchgmat, mv.view

        # Render the kernel template
        tpl = self.backend.lookup.get_template('pack')
        src = tpl.render(alignb=self.backend.alignb, fpdtype=m.dtype)

        # Build
        kern = self._build_kernel('pack_view', src, [np.int32]*3 + [np.intp]*5)

        class PackXchgViewKernel(ComputeKernel):
            def run(self, queue):
                # Kernel arguments
                args = [v.n, v.nvrow, v.nvcol, v.basedata, v.mapping,
                        v.cstrides, v.rstrides, m]
                args = [getattr(arg, 'data', arg) for arg in args]

                # Pack
                event = kern(queue.cl_queue_comp, (v.n,), None, *args)

                # Copy the packed buffer to the host
                cl.enqueue_copy(queue.cl_queue_copy, m.hdata, m.data,
                                is_blocking=False, wait_for=[event])

        return PackXchgViewKernel()

    def send_pack(self, mv, pid, tag):
        from mpi4py import MPI

        return self._sendrecv(mv, MPI.COMM_WORLD.Send_init, pid, tag)

    def recv_pack(self, mv, pid, tag):
        from mpi4py import MPI

        return self._sendrecv(mv, MPI.COMM_WORLD.Recv_init, pid, tag)

    def unpack(self, mv):
        class UnpackXchgMatrixKernel(ComputeKernel):
            def run(self, queue):
                cl.enqueue_copy(queue.cl_queue_comp, mv.data, mv.hdata,
                                is_blocking=False)

        return UnpackXchgMatrixKernel()
