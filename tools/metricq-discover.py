#!/usr/bin/env python3
# Copyright (c) 2020, ZIH, Technische Universitaet Dresden, Federal Republic of Germany
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
import datetime
import logging
from typing import Optional

import aio_pika
import click
import click_completion
import click_log
import humanize
from dateutil.parser import isoparse as parse_iso_datetime
from dateutil.tz import tzlocal

import metricq
from metricq.types import Timedelta

logger = metricq.get_logger()
logger.setLevel(logging.WARN)
click_log.basic_config(logger)
logger.handlers[0].formatter = logging.Formatter(
    fmt="%(asctime)s [%(levelname)-8s] [%(name)-20s] %(message)s"
)

click_completion.init()


class DiscoverResponse:
    def __init__(
        self,
        alive: bool = True,
        current_time: Optional[str] = None,
        starting_time: Optional[str] = None,
        uptime: Optional[int] = None,
        metricq_version: Optional[str] = None,
        hostname: Optional[str] = None,
    ):
        self.alive = alive
        self.metricq_version = metricq_version
        self.hostname = hostname

        self.current_time = self._parse_datetime(current_time)
        self.starting_time = self._parse_datetime(starting_time)
        self.uptime: Optional[datetime.timedelta] = None

        try:
            if uptime is None:
                self.uptime = self.current_time - self.starting_time
            else:
                self.uptime = (
                    datetime.timedelta(seconds=uptime)
                    if uptime < 1e9
                    else datetime.timedelta(microseconds=int(uptime // 1e3))
                )
        except (ValueError, TypeError):
            pass

    @classmethod
    def _parse_datetime(cls, iso_string) -> Optional[datetime.datetime]:
        if iso_string is None:
            return None
        else:
            try:
                dt = parse_iso_datetime(iso_string)
                return dt.astimezone(tzlocal()).replace(tzinfo=None)
            except (AttributeError, ValueError, TypeError, OverflowError) as e:
                logger.warning("Failed to parse ISO datestring ({}): {}", iso_string, e)
                return None

    def _fmt_parts(self):
        unknown_color = "bright_white"

        yield (
            click.style("✔️", fg="green") if self.alive else click.style("❌", fg="red")
        )

        try:
            yield f"up for {humanize.naturaldelta(self.uptime)}"
        except Exception:
            yield click.style("unknown uptime", fg=unknown_color)

        try:
            yield f"(started {humanize.naturalday(self.starting_time)})"
        except Exception as e:
            logger.warning(
                "Failed to convert {} to naturaltime: {}", self.starting_time, e
            )

        if self.metricq_version:
            yield f"running {self.metricq_version}"

        if self.hostname:
            yield f"on {self.hostname}"

    def __str__(self):
        return " ".join(self._fmt_parts())


def echo_status(token: str, msg: str):
    click.echo(f'{click.style(token, fg="cyan")}: {msg}')


class MetricQDiscover(metricq.Agent):
    def __init__(self, server, timeout: Timedelta, ignore_events):
        super().__init__("discover", server, add_uuid=True)
        self.timeout = timeout
        self.ignore_events = set(ignore_events)

    async def discover(self):
        await self.connect()
        await self.rpc_consume()

        self._management_broadcast_exchange = await self._management_channel.declare_exchange(
            name=self._management_broadcast_exchange_name,
            type=aio_pika.ExchangeType.FANOUT,
            durable=True,
        )

        await self.rpc(
            self._management_broadcast_exchange,
            "discover",
            response_callback=self.on_discover,
            function="discover",
            cleanup_on_response=False,
        )

        await asyncio.sleep(self.timeout.s)

    def on_discover(self, from_token, **kwargs):
        error = kwargs.get("error")
        if error is not None:
            if "error-responses" not in self.ignore_events:
                status = click.style("⚠", fg="yellow")
                echo_status(
                    from_token, f"{status} response indicated an error: {error}"
                )
        else:
            self.pretty_print(from_token, response=kwargs)

    def pretty_print(self, from_token, response: dict):
        logger.debug("response: {}", response)
        response = DiscoverResponse(
            alive=response.get("alive"),
            starting_time=response.get("startingTime"),
            current_time=response.get("currentTime"),
            uptime=response.get("uptime"),
            metricq_version=response.get("metricqVersion"),
            hostname=response.get("hostname"),
        )

        echo_status(from_token, str(response))


@click.command()
@click_log.simple_verbosity_option(logger)
@click.option("--server", default="amqp://localhost/")
@click.option("-t", "--timeout", default="30s")
@click.option(
    "--ignore",
    type=click.Choice(["error-responses"], case_sensitive=False),
    multiple=True,
)
def discover_command(server, timeout: str, ignore):
    d = MetricQDiscover(
        server, timeout=Timedelta.from_string(timeout), ignore_events=ignore
    )

    asyncio.run(d.discover())


if __name__ == "__main__":
    discover_command()
