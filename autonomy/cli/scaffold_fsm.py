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

"""
Implement a scaffold sub-command to scaffold ABCI skills.

This module patches the 'aea scaffold' command so to add a new subcommand for scaffolding a skill
 starting from FSM specification.
"""
import re
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from textwrap import dedent, indent
from typing import Dict, Set

import click
from aea.cli.add import add_item
from aea.cli.fingerprint import fingerprint_item
from aea.cli.scaffold import scaffold, scaffold_item
from aea.cli.utils.click_utils import registry_flag
from aea.cli.utils.context import Context
from aea.cli.utils.decorators import pass_ctx
from aea.configurations.base import (
    AgentConfig,
    SkillComponentConfiguration,
    SkillConfig,
)
from aea.configurations.constants import (
    DEFAULT_AEA_CONFIG_FILE,
    DEFAULT_SKILL_CONFIG_FILE,
    SKILL,
    SKILLS,
)

# the decoration does side-effect on the 'aea scaffold' command
from aea.configurations.data_types import CRUDCollection, PublicId

from autonomy.analyse.abci.app_spec import DFA
from autonomy.constants import ABSTRACT_ROUND_ABCI_SKILL_WITH_HASH


FILE_HEADER = """\
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
"""

ROUNDS_FILENAME = "rounds.py"
BEHAVIOURS_FILENAME = "behaviours.py"
MODELS_FILENAME = "models.py"
HANDLERS_FILENAME = "handlers.py"

DEGENERATE_ROUND = "DegenerateRound"
ABSTRACT_ROUND = "AbstractRound"


def _remove_quotes(input_str: str) -> str:
    """Remove single or double quotes from a string."""
    return input_str.replace("'", "").replace('"', "")


def _get_abci_app_cls_name_from_dfa(dfa: DFA) -> str:
    """Get the Abci app class name from a DFA object."""
    return dfa.label.split(".")[-1]


def _try_get_behaviour_cls_name_from_round_cls_name(round_cls_name: str) -> str:
    """
    Try to get the behaviour class name from the round class name.

    It tries to replace the suffix "Round" with "Behaviour".

    :param round_cls_name: the round class name
    :return: the new behaviour class name
    """
    return re.sub("(.*)Round", "\\1Behaviour", round_cls_name)


def _try_get_round_behaviour_cls_name_from_abci_app_cls_name(
    abci_app_cls_name: str,
) -> str:
    """
    Try to get the round behaviour class name from the Abci app class name.

    It tries to replace the suffix "AbciApp" with "RoundBehaviour".

    If it fails, returns "RoundBehaviour".

    :param abci_app_cls_name: the abci app class name
    :return: the new round behaviour class name
    """
    result = re.sub("(.*)AbciApp", "\\1RoundBehaviour", abci_app_cls_name)
    # if replacement did not work, return default round behaviour name
    if result == abci_app_cls_name:
        return "RoundBehaviour"
    return result


def _try_get_base_behaviour_cls_name_from_abci_app_cls_name(
    abci_app_cls_name: str,
) -> str:
    """
    Try to get the base behaviour class name from the Abci app class name.

    It tries to replace the suffix "AbciApp" with "BaseBehaviour".

    If it fails, returns "RoundBehaviour".

    :param abci_app_cls_name: the abci app class name
    :return: the new round behaviour class name
    """
    result = re.sub("(.*)AbciApp", "\\1BaseBehaviour", abci_app_cls_name)
    # if replacement did not work, return default round behaviour name
    if result == abci_app_cls_name:
        return "BaseBehaviour"
    return result


class AbstractFileGenerator(ABC):
    """An abstract class for file generators."""

    FILENAME: str

    def __init__(self, ctx: Context, skill_name: str, dfa: DFA) -> None:
        """Initialize the abstract file generator."""
        self.ctx = ctx
        self.skill_name = skill_name
        self.dfa = dfa

    @abstractmethod
    def get_file_content(self) -> str:
        """Get file content."""

    def write_file(self, output_dir: Path) -> None:
        """Write the file to output_dir/FILENAME."""
        (output_dir / self.FILENAME).write_text(self.get_file_content())


class RoundFileGenerator(AbstractFileGenerator):
    """File generator for 'rounds.py' modules."""

    FILENAME = ROUNDS_FILENAME

    ROUNDS_FILE_HEADER = dedent(
        """\
        \"\"\"This package contains the rounds of {FSMName}.\"\"\"

        from enum import Enum
        from typing import List, Optional, Set, Tuple

        from packages.valory.skills.abstract_round_abci.base import (
            AbciApp,
            AbciAppTransitionFunction,
            AbstractRound,
            AppState,
            BaseSynchronizedData,
            BaseTxPayload,
            DegenerateRound,
            EventToTimeout,
            TransactionType
        )

    """
    )

    SYNCHRONIZED_DATA_SECTION = dedent(
        """\
        class SynchronizedData(BaseSynchronizedData):
            \"\"\"
            Class to represent the synchronized data.

            This data is replicated by the tendermint application.
            \"\"\"

    """
    )

    ROUND_CLS_TEMPLATE = dedent(
        """\
        class {RoundCls}({ABCRoundCls}):
            {todo_abstract_round_cls}
            # TODO: set the following class attributes
            round_id: str
            allowed_tx_type: Optional[TransactionType]
            payload_attribute: str

            def end_block(self) -> Optional[Tuple[BaseSynchronizedData, Enum]]:
                \"\"\"Process the end of the block.\"\"\"
                raise NotImplementedError

            def check_payload(self, payload: BaseTxPayload) -> None:
                \"\"\"Check payload.\"\"\"
                raise NotImplementedError

            def process_payload(self, payload: BaseTxPayload) -> None:
                \"\"\"Process payload.\"\"\"
                raise NotImplementedError

    """
    )

    ABCI_APP_CLS_TEMPLATE = dedent(
        """\
        class {AbciAppCls}(AbciApp[Event]):
            initial_round_cls: AppState = {initial_round_cls}
            initial_states: Set[AppState] = {initial_states}
            transition_function: AbciAppTransitionFunction = {transition_function}
            final_states: Set[AppState] = {final_states}
            event_to_timeout: EventToTimeout = {{}}
            cross_period_persisted_keys: List[str] = []
    """
    )

    def get_file_content(self) -> str:
        """Scaffold the 'rounds.py' file."""
        rounds_header_section = self._get_rounds_header_section()
        event_section = self._get_event_section()
        synchronized_data_section = self._get_synchronized_data_section()
        rounds_section = self._get_rounds_section()
        abci_app_section = self._get_abci_app_section()

        # build final content
        rounds_file_content = "\n".join(
            [
                FILE_HEADER,
                rounds_header_section,
                event_section,
                synchronized_data_section,
                rounds_section,
                abci_app_section,
            ]
        )

        return rounds_file_content

    def _get_rounds_header_section(self) -> str:
        """Get the rounds header section."""
        return self.ROUNDS_FILE_HEADER.format(
            FSMName=_get_abci_app_cls_name_from_dfa(self.dfa)
        )

    def _get_rounds_section(self) -> str:
        """Get the round section of the module (i.e. the round classes)."""
        all_round_classes_str = []

        # add round classes
        for abci_round_name in self.dfa.states:
            abci_round_base_cls_name = (
                DEGENERATE_ROUND
                if abci_round_name in self.dfa.final_states
                else ABSTRACT_ROUND
            )
            todo_abstract_round_cls = ""
            if abci_round_base_cls_name == ABSTRACT_ROUND:
                todo_abstract_round_cls = "# TODO: replace AbstractRound with one of CollectDifferentUntilAllRound, CollectSameUntilAllRound, CollectSameUntilThresholdRound, CollectDifferentUntilThresholdRound, OnlyKeeperSendsRound, VotingRound"
            round_class_str = RoundFileGenerator.ROUND_CLS_TEMPLATE.format(
                RoundCls=abci_round_name,
                ABCRoundCls=abci_round_base_cls_name,
                todo_abstract_round_cls=todo_abstract_round_cls,
            )
            all_round_classes_str.append(round_class_str)

        # build final content
        return "\n".join(all_round_classes_str)

    def _get_event_section(self) -> str:
        """Get the event section of the module (i.e. the event enum class definition)."""
        class_header = "class Event(Enum):\n"
        events = [
            f'{event_name} = "{event_name.lower()}"'
            for event_name in self.dfa.alphabet_in
        ]
        class_body = indent("\n".join(events), " " * 4)
        enum_event_class = class_header + "\n" + class_body + "\n\n"
        return enum_event_class

    def _get_synchronized_data_section(self) -> str:
        """Get the event section of the module (i.e. the event enum class definition)."""
        return self.SYNCHRONIZED_DATA_SECTION

    def _get_abci_app_section(self) -> str:
        """Get the abci app section (i.e. the declaration of the AbciApp class)."""
        abci_app_cls_name = _get_abci_app_cls_name_from_dfa(self.dfa)
        return RoundFileGenerator.ABCI_APP_CLS_TEMPLATE.format(
            AbciAppCls=abci_app_cls_name,
            initial_round_cls=self.dfa.default_start_state,
            initial_states=_remove_quotes(str(self.dfa.start_states)),
            transition_function=self._parse_transition_func(),
            final_states=_remove_quotes(str(self.dfa.final_states)),
        )

    def _parse_transition_func(self) -> str:
        """Parse the transition function from the spec to a nested dictionary."""
        result: Dict[str, Dict[str, str]] = {}  # type: ignore
        for (round_cls_name, event_name), value in self.dfa.transition_func.items():
            result.setdefault(round_cls_name, {})[f"Event.{event_name}"] = value
        for state in self.dfa.states:
            if state not in result:
                result[state] = {}
        return _remove_quotes(str(result))


class BehaviourFileGenerator(AbstractFileGenerator):
    """File generator for 'behaviours.py' modules."""

    FILENAME = BEHAVIOURS_FILENAME

    BEHAVIOUR_FILE_HEADER = dedent(
        """\
        \"\"\"This package contains round behaviours of {FSMName}.\"\"\"

        from abc import abstractmethod
        from typing import Generator, Set, Type, cast

        from packages.valory.skills.abstract_round_abci.base import AbstractRound
        from packages.valory.skills.abstract_round_abci.behaviours import (
            AbstractRoundBehaviour,
            BaseBehaviour,
        )

        from packages.{scaffold_skill_author_name}.skills.{scaffold_skill_name}.models import Params
        from packages.{scaffold_skill_author_name}.skills.{scaffold_skill_name}.rounds import SynchronizedData, {AbciAppCls}

        """
    )

    BASE_BEHAVIOUR_CLS_TEMPLATE = dedent(
        """\
        class {BaseBehaviourCls}(BaseBehaviour):
            \"\"\"Base behaviour for the common apps' skill.\"\"\"

            @property
            def synchronized_data(self) -> SynchronizedData:
                \"\"\"Return the synchronized data.\"\"\"
                return cast(SynchronizedData, super().synchronized_data)

            @property
            def params(self) -> Params:
                \"\"\"Return the params.\"\"\"
                return cast(Params, super().params)

    """
    )

    BEHAVIOUR_CLS_TEMPLATE = dedent(
        """\
        class {BehaviourCls}({BaseBehaviourCls}):
            # TODO: set the following class attributes
            state_id: str
            behaviour_id: str
            matching_round: Type[AbstractRound]

            @abstractmethod
            def async_act(self) -> Generator:
                \"\"\"Do the act, supporting asynchronous execution.\"\"\"

    """
    )

    ROUND_BEHAVIOUR_CLS_TEMPLATE = dedent(
        """\
        class {RoundBehaviourCls}(AbstractRoundBehaviour):
            initial_behaviour_cls = {InitialBehaviourCls}
            abci_app_cls = {AbciAppCls}  # type: ignore
            behaviours: Set[Type[BaseBehaviour]] = {behaviours}
    """
    )

    def get_file_content(self) -> str:
        """Scaffold the 'rounds.py' file."""
        behaviours_header_section = self._get_behaviours_header_section()
        base_behaviour_section = self._get_base_behaviour_section()
        behaviours_section = self._get_behaviours_section()
        round_behaviour_section = self._get_round_behaviour_section()

        # build final content
        behaviours_file_content = "\n".join(
            [
                FILE_HEADER,
                behaviours_header_section,
                base_behaviour_section,
                behaviours_section,
                round_behaviour_section,
            ]
        )

        return behaviours_file_content

    def _get_behaviours_header_section(self) -> str:
        """Get the behaviours header section."""
        abci_app_cls_name = _get_abci_app_cls_name_from_dfa(self.dfa)
        return self.BEHAVIOUR_FILE_HEADER.format(
            FSMName=_get_abci_app_cls_name_from_dfa(self.dfa),
            scaffold_skill_author_name=self.ctx.agent_config.author,
            scaffold_skill_name=self.skill_name,
            AbciAppCls=abci_app_cls_name,
        )

    def _get_base_behaviour_section(self) -> str:
        """Get the base behaviour section."""
        abci_app_cls_name = _get_abci_app_cls_name_from_dfa(self.dfa)
        base_behaviour_cls_name = (
            _try_get_base_behaviour_cls_name_from_abci_app_cls_name(abci_app_cls_name)
        )
        return self.BASE_BEHAVIOUR_CLS_TEMPLATE.format(
            BaseBehaviourCls=base_behaviour_cls_name
        )

    def _get_behaviours_section(self) -> str:
        """Get the behaviours section of the module (i.e. the list of behaviour classes)."""
        all_behaviour_classes_str = []

        abci_app_cls_name = _get_abci_app_cls_name_from_dfa(self.dfa)

        # add behaviour classes
        for abci_round_name in self.dfa.states:
            # try to replace 'Round' suffix with 'Behaviour'
            abci_behaviour_name = _try_get_behaviour_cls_name_from_round_cls_name(
                abci_round_name
            )
            base_behaviour_cls_name = (
                _try_get_base_behaviour_cls_name_from_abci_app_cls_name(
                    abci_app_cls_name
                )
            )
            behaviour_class_str = BehaviourFileGenerator.BEHAVIOUR_CLS_TEMPLATE.format(
                BehaviourCls=abci_behaviour_name,
                BaseBehaviourCls=base_behaviour_cls_name,
            )
            all_behaviour_classes_str.append(behaviour_class_str)

        # build final content
        return "\n".join(all_behaviour_classes_str)

    def _get_behaviour_set(self) -> Set[str]:
        """Get the set of behaviour states (excluding final states)."""
        result: Set[str] = set()
        for abci_round_name in self.dfa.states:
            if abci_round_name in self.dfa.final_states:
                continue
            # try to replace 'Round' suffix with 'Behaviour'
            abci_behaviour_name = _try_get_behaviour_cls_name_from_round_cls_name(
                abci_round_name
            )
            result.add(abci_behaviour_name)
        return result

    def _get_round_behaviour_section(self) -> str:
        """Get the round behaviour section of the module (i.e. the declaration of the round behaviour class)."""
        abci_app_cls_name = _get_abci_app_cls_name_from_dfa(self.dfa)
        round_behaviour_cls_name = (
            _try_get_round_behaviour_cls_name_from_abci_app_cls_name(abci_app_cls_name)
        )
        initial_round_cls_name = self.dfa.default_start_state
        initial_behaviour_cls_name = _try_get_behaviour_cls_name_from_round_cls_name(
            initial_round_cls_name
        )
        return BehaviourFileGenerator.ROUND_BEHAVIOUR_CLS_TEMPLATE.format(
            RoundBehaviourCls=round_behaviour_cls_name,
            InitialBehaviourCls=initial_behaviour_cls_name,
            AbciAppCls=abci_app_cls_name,
            behaviours=_remove_quotes(str(self._get_behaviour_set())),
        )


class ModelsFileGenerator(AbstractFileGenerator):
    """File generator for 'models.py' modules."""

    FILENAME = MODELS_FILENAME

    MODEL_FILE_TEMPLATE = dedent(
        """\
        \"\"\"This module contains the shared state for the abci skill of {FSMName}.\"\"\"

        from typing import Any

        from packages.valory.skills.abstract_round_abci.models import BaseParams
        from packages.valory.skills.abstract_round_abci.models import Requests as BaseRequests
        from packages.valory.skills.abstract_round_abci.models import (
            SharedState as BaseSharedState,
        )
        from packages.{scaffold_skill_author_name}.skills.{scaffold_skill_name}.rounds import {AbciAppCls}


        class SharedState(BaseSharedState):
            \"\"\"Keep the current shared state of the skill.\"\"\"

            def __init__(self, *args: Any, **kwargs: Any) -> None:
                \"\"\"Initialize the state.\"\"\"
                super().__init__(*args, abci_app_cls={AbciAppCls}, **kwargs)


        Params = BaseParams
        Requests = BaseRequests
        """
    )

    def get_file_content(self) -> str:
        """Get the file content."""
        abci_app_cls_name = _get_abci_app_cls_name_from_dfa(self.dfa)
        return "\n".join(
            [
                FILE_HEADER,
                ModelsFileGenerator.MODEL_FILE_TEMPLATE.format(
                    FSMName=abci_app_cls_name,
                    AbciAppCls=abci_app_cls_name,
                    scaffold_skill_author_name=self.ctx.agent_config.author,
                    scaffold_skill_name=self.skill_name,
                ),
            ]
        )


class HandlersFileGenerator(AbstractFileGenerator):
    """File generator for 'handlers.py' modules."""

    FILENAME = HANDLERS_FILENAME

    HANDLERS_FILE = dedent(
        """\
        \"\"\"This module contains the handlers for the skill of {FSMName}.\"\"\"

        from packages.valory.skills.abstract_round_abci.handlers import (
            ABCIRoundHandler as BaseABCIRoundHandler,
        )
        from packages.valory.skills.abstract_round_abci.handlers import (
            ContractApiHandler as BaseContractApiHandler,
        )
        from packages.valory.skills.abstract_round_abci.handlers import (
            HttpHandler as BaseHttpHandler,
        )
        from packages.valory.skills.abstract_round_abci.handlers import (
            LedgerApiHandler as BaseLedgerApiHandler,
        )
        from packages.valory.skills.abstract_round_abci.handlers import (
            SigningHandler as BaseSigningHandler,
        )
        from packages.valory.skills.abstract_round_abci.handlers import (
            TendermintHandler as BaseTendermintHandler,
        )


        ABCIRoundHandler = BaseABCIRoundHandler
        HttpHandler = BaseHttpHandler
        SigningHandler = BaseSigningHandler
        LedgerApiHandler = BaseLedgerApiHandler
        ContractApiHandler = BaseContractApiHandler
        TendermintHandler = BaseTendermintHandler
        """
    )

    def get_file_content(self) -> str:
        """Get the file content."""
        abci_app_cls_name = _get_abci_app_cls_name_from_dfa(self.dfa)
        return "\n".join(
            [
                FILE_HEADER,
                HandlersFileGenerator.HANDLERS_FILE.format(FSMName=abci_app_cls_name),
            ]
        )


class SkillConfigUpdater:  # pylint: disable=too-few-public-methods
    """Update the skill configuration according to the Abci classes."""

    def __init__(self, ctx: Context, skill_dir: Path, dfa: DFA) -> None:
        """
        Initialize the skill config updater.

        :param ctx: the AEA CLI context object.
        :param skill_dir: the directory of the AEA skill package.
        :param dfa: the DFA object.
        """
        self.ctx = ctx
        self.skill_dir = skill_dir
        self.dfa = dfa

        self.skill_config_path = self.skill_dir / DEFAULT_SKILL_CONFIG_FILE

    def update(self) -> None:
        """Update the skill configuration file."""
        config = self.ctx.skill_loader.load(self.skill_config_path.open())
        self._update_behaviours(config)
        self._update_handlers(config)
        self._update_models(config)
        self._update_dependencies(config)
        self.ctx.skill_loader.dump(config, self.skill_config_path.open("w"))
        fingerprint_item(self.ctx, SKILL, config.public_id)

    def _update_behaviours(self, config: SkillConfig) -> None:
        """Update the behaviours section of the skill configuration."""
        config.behaviours = CRUDCollection[SkillComponentConfiguration]()
        abci_app_cls_name = _get_abci_app_cls_name_from_dfa(self.dfa)
        round_behaviour_cls_name = _try_get_behaviour_cls_name_from_round_cls_name(
            abci_app_cls_name
        )
        main_config = SkillComponentConfiguration(round_behaviour_cls_name)
        config.behaviours.create("main", main_config)

    def _update_handlers(  # pylint: disable=no-self-use
        self, config: SkillConfig
    ) -> None:
        """Update the handlers section of the skill configuration."""
        config.handlers = CRUDCollection[SkillComponentConfiguration]()
        config.handlers.create("abci", SkillComponentConfiguration("ABCIRoundHandler"))
        config.handlers.create(
            "contract_api", SkillComponentConfiguration("ContractApiHandler")
        )
        config.handlers.create("http", SkillComponentConfiguration("HttpHandler"))
        config.handlers.create(
            "ledger_api", SkillComponentConfiguration("LedgerApiHandler")
        )
        config.handlers.create("signing", SkillComponentConfiguration("SigningHandler"))
        config.handlers.create(
            "tendermint", SkillComponentConfiguration("TendermintHandler")
        )

    def _update_models(  # pylint: disable=no-self-use
        self, config: SkillConfig
    ) -> None:
        """Update the models section of the skill configuration."""
        config.models = CRUDCollection[SkillComponentConfiguration]()
        config.models.create("state", SkillComponentConfiguration("SharedState"))
        config.models.create("requests", SkillComponentConfiguration("Requests"))
        config.models.create("params", SkillComponentConfiguration("Params"))

    def _update_dependencies(self, config: SkillConfig) -> None:
        """Update skill dependencies."""
        # retrieve the actual valory/abstract_round_abci package
        agent_config = self._load_agent_config()
        abstract_round_abci = [
            public_id
            for public_id in agent_config.skills
            if public_id.author == "valory" and public_id.name == "abstract_round_abci"
        ][0]
        config.skills.add(abstract_round_abci)

    def _load_agent_config(self) -> AgentConfig:
        """Load the current agent configuration."""
        with (Path(self.ctx.cwd) / DEFAULT_AEA_CONFIG_FILE).open() as f:
            return self.ctx.agent_loader.load(f)


class ScaffoldABCISkill:
    """Utility class that implements the scaffolding of the ABCI skill."""

    def __init__(self, ctx: Context, skill_name: str, dfa: DFA) -> None:
        """Initialize the utility class."""
        self.ctx = ctx
        self.skill_name = skill_name
        self.dfa = dfa

    @property
    def skill_dir(self) -> Path:
        """Get the directory to the skill."""
        return Path(SKILLS, self.skill_name)

    def do_scaffolding(self) -> None:
        """Do the scaffolding."""
        self._scaffold_rounds()
        self._scaffold_behaviours()
        self._scaffold_models()
        self._scaffold_handlers()

        # remove original 'my_model.py' file
        shutil.rmtree(self.skill_dir / "my_model.py", ignore_errors=True)

        self._remove_pycache()
        self._update_config()

    def _scaffold_rounds(self) -> None:
        """Scaffold the 'rounds.py' module."""
        click.echo(f"Generating module {RoundFileGenerator.FILENAME}...")
        RoundFileGenerator(self.ctx, self.skill_name, self.dfa).write_file(
            self.skill_dir
        )

    def _scaffold_behaviours(self) -> None:
        """Scaffold the 'behaviours.py' module."""
        click.echo(f"Generating module {BehaviourFileGenerator.FILENAME}...")
        BehaviourFileGenerator(self.ctx, self.skill_name, self.dfa).write_file(
            self.skill_dir
        )

    def _scaffold_models(self) -> None:
        """Scaffold the 'models.py' module."""
        click.echo(f"Generating module {ModelsFileGenerator.FILENAME}...")
        ModelsFileGenerator(self.ctx, self.skill_name, self.dfa).write_file(
            self.skill_dir
        )

    def _scaffold_handlers(self) -> None:
        """Scaffold the 'handlers.py' module."""
        click.echo(f"Generating module {HandlersFileGenerator.FILENAME}...")
        HandlersFileGenerator(self.ctx, self.skill_name, self.dfa).write_file(
            self.skill_dir
        )

    def _update_config(self) -> None:
        """Update the skill configuration."""
        click.echo("Updating skill configuration...")
        SkillConfigUpdater(self.ctx, self.skill_dir, self.dfa).update()

    def _remove_pycache(self) -> None:
        """Remove __pycache__ folders."""
        for path in self.skill_dir.rglob("*__pycache__*"):
            shutil.rmtree(path, ignore_errors=True)


def _add_abstract_round_abci_if_not_present(ctx: Context) -> None:
    """Add 'abstract_round_abci' skill if not present."""
    abstract_round_abci_public_id = PublicId.from_str(
        ABSTRACT_ROUND_ABCI_SKILL_WITH_HASH
    )
    if abstract_round_abci_public_id.to_latest() not in {
        public_id.to_latest() for public_id in ctx.agent_config.skills
    }:
        click.echo(
            "Skill valory/abstract_round_abci not found in agent dependencies, adding it..."
        )
        add_item(ctx, SKILL, abstract_round_abci_public_id)


# Scaffolding of tests
class RoundTestsFileGenerator(RoundFileGenerator):
    """RoundTestsFileGenerator"""

    FILENAME = "tests_" + ROUNDS_FILENAME

    ROUNDS_FILE_HEADER = dedent(
        """\
        \"\"\"This package contains the tests for rounds of {FSMName}.\"\"\"

        from typing import Any, Dict, List, Callable, Hashable
        from dataclasses import dataclass, field

        import pytest

        # TODO: define and import specific payloads explicitly by name
        from packages.{author}.skills.{skill_name}.payloads import *
        from packages.{author}.skills.{skill_name}.rounds import (
            Event,
            SynchronizedData,
            {non_degenerate_rounds}
        )
        from packages.valory.skills.abstract_round_abci.base import (
            BaseTxPayload,
        )
        from tests.test_skills.test_abstract_round_abci.test_base_rounds import (
            BaseRoundTestClass,
            BaseOnlyKeeperSendsRoundTest,
            BaseCollectDifferentUntilThresholdRoundTest,
            BaseCollectSameUntilThresholdRoundTest,
         )


        @dataclass
        class RoundTestCase:
            \"\"\"RoundTestCase\"\"\"

            initial_data: Dict[str, Hashable]
            payloads: BaseTxPayload
            final_data: Dict[str, Hashable]
            event: Event
            synchronized_data_attr_checks: List[Callable] = field(default_factory=list)


        MAX_PARTICIPANTS: int = 4

    """
    )

    BASE_CLASS = dedent(
        """\
        class Base{FSMName}RoundTestClass(BaseRoundTestClass):
            \"\"\"Base test class for {FSMName} rounds.\"\"\"

            synchronized_data: SynchronizedData
            _synchronized_data_class = SynchronizedData
            _event_class = Event

            def run_test(self, test_case: RoundTestCase, **kwargs) -> None:
                \"\"\"Run the test\"\"\"

                self.synchronized_data.update(**test_case.initial_data)

                test_round = self.round_class(
                    synchronized_data=self.synchronized_data,
                    consensus_params=self.consensus_params,
                )

                self._complete_run(
                    self._test_round(
                        test_round=test_round,
                        round_payloads=test_case.payloads,
                        synchronized_data_update_fn=lambda sync_data, _: sync_data.update(**test_case.final_data),
                        synchronized_data_attr_checks=test_case.synchronized_data_attr_checks,
                        exit_event=test_case.event,
                        **kwargs,  # varies per BaseRoundTestClass child
                    )
                )

            """
    )

    ROUND_CLS_TEMPLATE = dedent(
        """\
        class Test{RoundCls}(Base{FSMName}RoundTestClass):
            \"\"\"Tests for {RoundCls}.\"\"\"

            round_class = {RoundCls}

            # TODO: provide test cases
            @pytest.mark.parametrize("test_case, kwargs", [])
            def test_run(self, test_case: RoundTestCase, **kwargs: Any) -> None:
                \"\"\"Run tests.\"\"\"

                self.run_test(test_case, **kwargs)

    """
    )

    def get_file_content(self) -> str:
        """Scaffold the 'test_rounds.py' file."""

        rounds_header_section = self._get_rounds_header_section()
        rounds_section = self._get_rounds_section()

        rounds_file_content = "\n".join(
            [
                FILE_HEADER,
                rounds_header_section,
                rounds_section,
            ]
        )

        return rounds_file_content

    def _get_rounds_header_section(self) -> str:
        """Get the rounds header section."""

        author = "valory"
        rounds = self.dfa.states - self.dfa.final_states

        return self.ROUNDS_FILE_HEADER.format(
            FSMName=_get_abci_app_cls_name_from_dfa(self.dfa),
            author=author,
            skill_name=self.skill_name,
            non_degenerate_rounds=indent(",\n".join(rounds), " " * 4).strip() + ",",
        )

    def _get_rounds_section(self) -> str:
        """Get rounds section"""

        app_name = _get_abci_app_cls_name_from_dfa(self.dfa)
        fsm_name = app_name.strip("AbciApp")  # noqa: B005
        all_round_classes_str = [self.BASE_CLASS.format(FSMName=fsm_name)]

        for abci_round_name in self.dfa.states - self.dfa.final_states:
            round_class_str = self.ROUND_CLS_TEMPLATE.format(
                FSMName=fsm_name,
                RoundCls=abci_round_name,
            )
            all_round_classes_str.append(round_class_str)

        return "\n".join(all_round_classes_str)


class BehaviourTestsFileGenerator(BehaviourFileGenerator):
    """File generator for 'test_behaviours.py' modules."""

    FILENAME = "test_" + BEHAVIOURS_FILENAME

    BEHAVIOUR_FILE_HEADER = dedent(
        """\
        \"\"\"This package contains round behaviours of {AbciAppCls}.\"\"\"

        from pathlib import Path
        from typing import Any, Dict, Hashable, Optional, Type
        from dataclasses import dataclass

        import pytest

        from packages.valory.skills.abstract_round_abci.base import AbciAppDB
        from packages.valory.skills.abstract_round_abci.behaviours import (
            AbstractRoundBehaviour,
            BaseBehaviour,
            make_degenerate_behaviour,
        )
        from packages.{author}.skills.{skill_name}.behaviours import (
            {FSMName}BaseBehaviour,
            {non_degenerate_behaviours},
        )
        from packages.{author}.skills.{skill_name}.rounds import (
            SynchronizedData,
            DegenerateRound,
            Event,
            {AbciAppCls},
            {rounds},
        )

        from tests.conftest import ROOT_DIR
        from tests.test_skills.test_abstract_round_abci.test_tools.base import (
            FSMBehaviourBaseCase,
        )

        """
    )

    BASE_CLASS = dedent(
        """\
        class Base{FSMName}Test(FSMBehaviourBaseCase):
            \"\"\"Base test case.\"\"\"

            path_to_skill = Path(ROOT_DIR, "packages", "{author}", "skills", "{skill_name}")

            behaviour: {FSMName}BaseBehaviour
            behaviour_class: Type[{FSMName}BaseBehaviour]
            next_behaviour_class: Type[{FSMName}BaseBehaviour]
            synchronized_data: SynchronizedData
            done_event = Event.DONE

    """
    )

    BEHAVIOUR_CLS_TEMPLATE = dedent(
        """\
        class Test{BehaviourCls}(Base{FSMName}):
            \"\"\"Tests {BehaviourCls}\"\"\"

            # TODO: set next_behaviour_class
            behaviour_class: Type[BaseBehaviour] = {BehaviourCls}
            next_behaviour_class: Type[BaseBehaviour] = ...

    """
    )

    def get_file_content(self) -> str:
        """Scaffold the 'test_behaviours.py' file."""

        behaviour_header_section = self._get_behaviour_header_section()
        behaviour_section = self._get_behaviour_section()

        behaviour_file_content = "\n".join(
            [
                FILE_HEADER,
                behaviour_header_section,
                behaviour_section,
            ]
        )

        return behaviour_file_content

    @property
    def abci_app_name(self) -> str:
        """AbciApp class name"""
        return _get_abci_app_cls_name_from_dfa(self.dfa)

    @property
    def fsm_name(self) -> str:
        """FSM base name"""
        return self.abci_app_name.rstrip("AbciApp")  # noqa: B005

    @property
    def non_degenerate_behaviours(self) -> Set[str]:
        """Non-degenerate behaviours"""

        rounds = self.dfa.states - self.dfa.final_states
        return {r.replace("Round", "Behaviour") for r in rounds}

    def _get_behaviour_header_section(self) -> str:
        """Get the rounds header section."""

        author = "valory"
        rounds = self.dfa.states
        behaviours = self.non_degenerate_behaviours
        return self.BEHAVIOUR_FILE_HEADER.format(
            AbciAppCls=self.abci_app_name,
            FSMName=self.fsm_name,
            author=author,
            skill_name=self.skill_name,
            rounds=indent(",\n".join(rounds), " " * 4).strip(),
            non_degenerate_behaviours=indent(",\n".join(behaviours), " " * 4).strip(),
        )

    def _get_behaviour_section(self) -> str:
        """Get behaviour section"""

        author = "valory"
        all_behaviour_classes_str = [self.BASE_CLASS.format(
            FSMName=self.fsm_name,
            author=author,
            skill_name=self.skill_name,
        )]

        for abci_behaviour_name in self.non_degenerate_behaviours:
            round_class_str = self.BEHAVIOUR_CLS_TEMPLATE.format(
                FSMName=self.fsm_name,
                BehaviourCls=abci_behaviour_name,
            )
            all_behaviour_classes_str.append(round_class_str)

        return "\n".join(all_behaviour_classes_str)


class ScaffoldABCISkillTests(ScaffoldABCISkill):
    """ScaffoldABCISkillTests"""

    @property
    def skill_test_dir(self) -> Path:
        """Get the directory to the skill tests."""
        return self.skill_dir / "tests"

    def do_scaffolding(self) -> None:
        """Do the scaffolding."""
        self.skill_test_dir.mkdir()
        self._scaffold_rounds()
        self._scaffold_behaviours()

    def _scaffold_rounds(self) -> None:
        """Scaffold the tests for rounds"""
        click.echo(f"Generating test module {RoundTestsFileGenerator.FILENAME}...")
        RoundTestsFileGenerator(self.ctx, self.skill_name, self.dfa).write_file(
            self.skill_test_dir
        )

    def _scaffold_behaviours(self) -> None:
        """Scaffold the tests for behaviour"""
        click.echo(f"Generating test module {BehaviourTestsFileGenerator.FILENAME}...")
        BehaviourTestsFileGenerator(self.ctx, self.skill_name, self.dfa).write_file(
            self.skill_test_dir
        )


@scaffold.command()  # noqa
@registry_flag()
@click.argument("skill_name", type=str, required=True)
@click.option("--spec", type=click.Path(exists=True, dir_okay=False), required=True)
@pass_ctx
def fsm(ctx: Context, registry: str, skill_name: str, spec: str) -> None:
    """Add an ABCI skill scaffolding from an FSM specification."""
    ctx.registry_type = registry
    # check abstract_round_abci is in dependencies; if not, add it
    _add_abstract_round_abci_if_not_present(ctx)

    # scaffold AEA skill - as usual
    scaffold_item(ctx, SKILL, skill_name)

    # process FSM specification
    spec_path = Path(spec)
    with spec_path.open(encoding="utf-8") as fp:
        dfa = DFA.load(fp, input_format="yaml")

    ScaffoldABCISkill(ctx, skill_name, dfa).do_scaffolding()
    ScaffoldABCISkillTests(ctx, skill_name, dfa).do_scaffolding()
