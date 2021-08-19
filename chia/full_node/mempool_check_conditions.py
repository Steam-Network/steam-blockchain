import logging
from typing import Dict, Optional
from clvm_rs import STRICT_MODE as MEMPOOL_MODE

from chia.consensus.cost_calculator import NPCResult, SpendBundleConditions
from chia.full_node.generator import create_generator_args, setup_generator_args
from chia.types.blockchain_format.program import NIL
from chia.types.coin_record import CoinRecord
from chia.types.generator_types import BlockGenerator
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.errors import Err
from chia.util.ints import uint32, uint64, uint16
from chia.wallet.puzzles.generator_loader import GENERATOR_FOR_SINGLE_COIN_MOD
from chia.wallet.puzzles.rom_bootstrap_generator import get_generator

GENERATOR_MOD = get_generator()

log = logging.getLogger(__name__)


def get_name_puzzle_conditions(
    generator: BlockGenerator, max_cost: int, *, cost_per_byte: int, mempool_mode: bool
) -> NPCResult:
    block_program, block_program_args = setup_generator_args(generator)
    size_cost = len(bytes(generator.program)) * cost_per_byte
    max_cost -= size_cost
    if max_cost < 0:
        return NPCResult(uint16(Err.INVALID_BLOCK_COST.value), None, uint64(0))

    flags = MEMPOOL_MODE if mempool_mode else 0
    try:
        err, result = GENERATOR_MOD.run_as_generator(max_cost, flags, block_program, block_program_args)
        assert (err is None) != (result is None)
        if err is not None:
            return NPCResult(uint16(err), None, uint64(0))
        else:
            return NPCResult(None, result, uint64(result.cost + size_cost))
    except BaseException as e:
        log.debug(f"get_name_puzzle_condition failed: {e}")
        return NPCResult(uint16(Err.GENERATOR_RUNTIME_ERROR.value), None, uint64(0))


def get_puzzle_and_solution_for_coin(generator: BlockGenerator, coin_name: bytes, max_cost: int):
    try:
        block_program = generator.program
        if not generator.generator_args:
            block_program_args = [NIL]
        else:
            block_program_args = create_generator_args(generator.generator_refs())

        cost, result = GENERATOR_FOR_SINGLE_COIN_MOD.run_with_cost(
            max_cost, block_program, block_program_args, coin_name
        )
        puzzle = result.first()
        solution = result.rest().first()
        return None, puzzle, solution
    except Exception as e:
        return e, None, None


def mempool_check_time_locks(
    removal_coin_records: Dict[bytes32, CoinRecord],
    bundle_conds: SpendBundleConditions,
    prev_transaction_block_height: uint32,
    timestamp: uint64,
) -> Optional[Err]:
    """
    Check all time and height conditions against current state.
    """

    if prev_transaction_block_height < bundle_conds.height_absolute:
        return Err.ASSERT_HEIGHT_ABSOLUTE_FAILED
    if timestamp < bundle_conds.seconds_absolute:
        return Err.ASSERT_SECONDS_ABSOLUTE_FAILED

    for spend in bundle_conds.spends:
        unspent = removal_coin_records[spend.coin_id]
        if spend.height_relative is not None:
            if prev_transaction_block_height < unspent.confirmed_block_index + spend.height_relative:
                return Err.ASSERT_HEIGHT_RELATIVE_FAILED
        if timestamp < unspent.timestamp + spend.seconds_relative:
            return Err.ASSERT_SECONDS_RELATIVE_FAILED
    return None
