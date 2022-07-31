# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2022 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""Utilities for the autonomy test tools."""

import logging
import time

import requests

from autonomy.constants import DEFAULT_REQUESTS_TIMEOUT, MAX_RETRIES


def tendermint_health_check(
    url: str,
    max_retries: int = MAX_RETRIES,
    sleep_interval: float = 1.0,
    timeout: float = DEFAULT_REQUESTS_TIMEOUT,
) -> bool:
    """Wait until a Tendermint RPC server is up."""
    attempt = 0
    while attempt < max_retries:
        try:
            response = requests.get(url + "/health", timeout=timeout)
            assert response.status_code == 200
            return True
        except (AssertionError, requests.exceptions.ConnectionError):
            attempt += 1
        logging.debug(
            f"Health-check attempt {attempt - 1} for {url} failed. Retrying in {sleep_interval} seconds..."
        )
        time.sleep(sleep_interval)
    return False
