# Copyright (c) 2018, ZIH,
# Technische Universitaet Dresden,
# Federal Republic of Germany
#
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:
#
#     * Redistributions of source code must retain the above copyright notice,
#       this list of conditions and the following disclaimer.
#     * Redistributions in binary form must reproduce the above copyright notice,
#       this list of conditions and the following disclaimer in the documentation
#       and/or other materials provided with the distribution.
#     * Neither the name of metricq nor the names of its contributors
#       may be used to endorse or promote products derived from this software
#       without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR
# CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
# EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
# PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR
# PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF
# LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING
# NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import asyncio
from time import time

from .agent import Agent
from .logging import get_logger
from .rpc import rpc_handler
from .types import to_timestamp

logger = get_logger(__name__)


class Client(Agent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.starting_time = time()

    @property
    def name(self):
        return 'client-' + self.token

    async def connect(self):
        await super().connect()

        self._management_broadcast_exchange = await self._management_channel.declare_exchange(
            name=self._management_broadcast_exchange_name, passive=True)
        self._management_exchange = await self._management_channel.declare_exchange(
            name=self._management_exchange_name, passive=True)

        await self.management_rpc_queue.bind(
            exchange=self._management_broadcast_exchange, routing_key="#")

        await self.rpc_consume()

    async def rpc(self, function, response_callback, **kwargs):
        await self.rpc(function, response_callback,
                       exchange=self._management_exchange, routing_key=function,
                       cleanup_on_response=True, **kwargs)

    async def rpc_response(self, function, **kwargs):
        request_future = asyncio.Future(loop=self.event_loop)
        await self.rpc(function,
                       lambda **response: request_future.set_result(response),
                       **kwargs)
        return await asyncio.wait_for(request_future, timeout=60)

    @rpc_handler('discover')
    async def _on_discover(self, **kwargs):
        logger.info('responding to discover')
        t = time()
        return {
            'alive': True,
            'uptime': to_timestamp(t - self.starting_time),
            'time': to_timestamp(t),
        }
