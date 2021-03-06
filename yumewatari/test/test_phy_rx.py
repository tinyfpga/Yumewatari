import unittest
from migen import *

from ..gateware.serdes import *
from ..gateware.serdes import K, D
from ..gateware.phy_rx import *
from . import simulation_test


class PCIePHYRXTestbench(Module):
    def __init__(self, ratio=1):
        self.submodules.lane = PCIeSERDESInterface(ratio)
        self.submodules.phy  = PCIePHYRX(self.lane)

    def do_finalize(self):
        self.states = {v: k for k, v in self.phy.parser.fsm.encoding.items()}

    def phy_state(self):
        return self.states[(yield self.phy.parser.fsm.state)]

    def transmit(self, symbols):
        for i, word in enumerate(symbols):
            if i > 0:
                assert (yield self.phy.error) == 0
            if isinstance(word, tuple):
                for j, symbol in enumerate(word):
                    yield self.lane.rx_symbol.part(j * 9, 9).eq(symbol)
            else:
                yield self.lane.rx_symbol.eq(word)
            yield


class _PCIePHYRXTestCase(unittest.TestCase):
    def assertState(self, tb, state):
        self.assertEqual((yield from tb.phy_state()), state)

    def assertSignal(self, signal, value):
        self.assertEqual((yield signal), value)


class PCIePHYRXGear1xTestCase(_PCIePHYRXTestCase):
    def setUp(self):
        self.tb = PCIePHYRXTestbench()

    def simulationSetUp(self, tb):
        yield tb.lane.rx_valid.eq(1)

    @simulation_test
    def test_rx_tsn_cycle_by_cycle(self, tb):
        yield tb.lane.rx_symbol.eq(K(28,5))
        yield
        yield from self.assertState(tb, "COMMA")
        yield tb.lane.rx_symbol.eq(D(1,0))
        yield
        yield from self.assertState(tb, "TSn-LINK/SKP-0")
        yield tb.lane.rx_symbol.eq(D(2,0))
        yield
        yield from self.assertSignal(tb.phy._tsZ.link.valid, 1)
        yield from self.assertSignal(tb.phy._tsZ.link.number, 1)
        yield from self.assertState(tb, "TSn-LANE")
        yield tb.lane.rx_symbol.eq(0xff)
        yield
        yield from self.assertSignal(tb.phy._tsZ.lane.valid, 1)
        yield from self.assertSignal(tb.phy._tsZ.lane.number, 2)
        yield from self.assertState(tb, "TSn-FTS")
        yield tb.lane.rx_symbol.eq(0b0010)
        yield
        yield from self.assertSignal(tb.phy._tsZ.n_fts, 0xff)
        yield from self.assertState(tb, "TSn-RATE")
        yield tb.lane.rx_symbol.eq(0b1111)
        yield
        yield from self.assertSignal(tb.phy._tsZ.rate.gen1, 1)
        yield from self.assertState(tb, "TSn-CTRL")
        yield tb.lane.rx_symbol.eq(D(5,2))
        yield
        yield from self.assertSignal(tb.phy._tsZ.ctrl.hot_reset, 1)
        yield from self.assertSignal(tb.phy._tsZ.ctrl.disable_link, 1)
        yield from self.assertSignal(tb.phy._tsZ.ctrl.loopback, 1)
        yield from self.assertSignal(tb.phy._tsZ.ctrl.disable_scrambling, 1)
        yield from self.assertState(tb, "TSn-ID0")
        yield tb.lane.rx_symbol.eq(D(5,2))
        yield
        yield from self.assertSignal(tb.phy._tsZ.ts_id, 1)
        yield from self.assertState(tb, "TSn-ID1")
        for n in range(2, 10):
            yield tb.lane.rx_symbol.eq(D(5,2))
            yield
            yield from self.assertState(tb, "TSn-ID%d" % n)
        yield tb.lane.rx_symbol.eq(K(28,5))
        yield
        yield from self.assertSignal(tb.phy._tsZ.valid, 1)
        yield from self.assertState(tb, "COMMA")

    def assertTSnState(self, tsN, valid=1, link_valid=0, link_number=0,
                       lane_valid=0, lane_number=0, n_fts=0, rate_gen1=0, rate_gen2=0,
                       ctrl_hot_reset=0, ctrl_disable_link=0, ctrl_loopback=0,
                       ctrl_disable_scrambling=0,
                       ts_id=0):
        yield from self.assertSignal(tsN.valid,           valid)
        yield from self.assertSignal(tsN.link.valid,      link_valid)
        yield from self.assertSignal(tsN.lane.valid,      lane_valid)
        yield from self.assertSignal(tsN.n_fts,           n_fts)
        yield from self.assertSignal(tsN.rate.gen1,       rate_gen1)
        yield from self.assertSignal(tsN.rate.gen2,       rate_gen2)
        yield from self.assertSignal(tsN.ctrl.hot_reset,            ctrl_hot_reset)
        yield from self.assertSignal(tsN.ctrl.disable_link,         ctrl_disable_link)
        yield from self.assertSignal(tsN.ctrl.loopback,             ctrl_loopback)
        yield from self.assertSignal(tsN.ctrl.disable_scrambling,   ctrl_disable_scrambling)
        yield from self.assertSignal(tsN.ts_id,           ts_id)

    def assertError(self, tb):
        yield from self.assertSignal(tb.phy.error, 1)
        yield
        yield from self.assertSignal(tb.phy._tsZ.valid, 0)
        yield from self.assertState(tb, "COMMA")

    @simulation_test
    def test_rx_ts1_empty_valid(self, tb):
        yield from self.tb.transmit([
            K(28,5), K(23,7), K(23,7), 0, 0b0000, 0b0000, *[D(10,2) for _ in range(10)],
            K(28,5),
        ])
        yield from self.assertTSnState(tb.phy._tsZ, ts_id=0)

    @simulation_test
    def test_rx_ts2_empty_valid(self, tb):
        yield from self.tb.transmit([
            K(28,5), K(23,7), K(23,7), 0, 0b0000, 0b0000, *[D(5,2) for _ in range(10)],
            K(28,5),
        ])
        yield from self.assertTSnState(tb.phy._tsZ, ts_id=1)

    @simulation_test
    def test_rx_ts1_inverted_valid(self, tb):
        yield from self.tb.transmit([
            K(28,5), K(23,7), K(23,7), D(0,0), D(0,0), D(0,0), *[D(21,5) for _ in range(10)],
            K(28,5),
        ])
        yield from self.assertSignal(tb.lane.rx_invert, 1)
        yield from self.assertTSnState(tb.phy._tsZ)

    @simulation_test
    def test_rx_ts2_inverted_valid(self, tb):
        yield from self.tb.transmit([
            K(28,5), K(23,7), K(23,7), D(0,0), D(0,0), D(0,0), *[D(26,5) for _ in range(10)],
            K(28,5),
        ])
        yield from self.assertSignal(tb.lane.rx_invert, 1)
        yield from self.assertTSnState(tb.phy._tsZ)

    @simulation_test
    def test_rx_ts1_link_valid(self, tb):
        yield from self.tb.transmit([
            K(28,5), 0xaa, K(23,7), 0, 0b0000, 0b0000, *[D(10,2) for _ in range(10)],
            K(28,5),
        ])
        yield from self.assertTSnState(tb.phy._tsZ,
            link_valid=1, link_number=0xaa)

    @simulation_test
    def test_rx_ts1_link_invalid(self, tb):
        yield from self.tb.transmit([
            K(28,5), 0x1ee,
        ])
        yield from self.assertError(tb)

    @simulation_test
    def test_rx_ts1_lane_valid(self, tb):
        yield from self.tb.transmit([
            K(28,5), 0xaa, 0x1a, 0, 0b0000, 0b0000, *[D(10,2) for _ in range(10)],
            K(28,5),
        ])
        yield from self.assertTSnState(tb.phy._tsZ,
            link_valid=1, link_number=0xaa,
            lane_valid=1, lane_number=0x1a)

    @simulation_test
    def test_rx_ts1_lane_invalid(self, tb):
        yield from self.tb.transmit([
            K(28,5), K(23,7), 0x1ee,
        ])
        yield from self.assertError(tb)

    @simulation_test
    def test_rx_ts1_n_fts_valid(self, tb):
        yield from self.tb.transmit([
            K(28,5), 0xaa, 0x1a, 0xff, 0b0000, 0b0000, *[D(10,2) for _ in range(10)],
            K(28,5),
        ])
        yield from self.assertTSnState(tb.phy._tsZ,
            link_valid=1, link_number=0xaa,
            lane_valid=1, lane_number=0x1a,
            n_fts=255)

    @simulation_test
    def test_rx_ts1_n_fts_invalid(self, tb):
        yield from self.tb.transmit([
            K(28,5), K(23,7), K(23,7), 0x1ee
        ])
        yield from self.assertError(tb)

    @simulation_test
    def test_rx_ts1_n_rate_valid(self, tb):
        yield from self.tb.transmit([
            K(28,5), 0xaa, 0x1a, 0xff, 0b0010, 0b0000, *[D(10,2) for _ in range(10)],
            K(28,5),
        ])
        yield from self.assertTSnState(tb.phy._tsZ,
            link_valid=1, link_number=0xaa,
            lane_valid=1, lane_number=0x1a,
            n_fts=255,
            rate_gen1=1)

    @simulation_test
    def test_rx_ts1_n_rate_invalid(self, tb):
        yield from self.tb.transmit([
            K(28,5), K(23,7), K(23,7), 0xff, 0x1ee
        ])
        yield from self.assertError(tb)

    @simulation_test
    def test_rx_ts1_ctrl_valid(self, tb):
        for (ctrl, bit) in (
            ("ctrl_hot_reset",          0b0001),
            ("ctrl_disable_link",       0b0010),
            ("ctrl_loopback",           0b0100),
            ("ctrl_disable_scrambling", 0b1000),
        ):
            yield from self.tb.transmit([
                K(28,5), 0xaa, 0x1a, 0xff, 0b0010, bit, *[D(10,2) for _ in range(10)],
            ])
            yield from self.assertTSnState(tb.phy._tsZ,
                link_valid=1, link_number=0xaa,
                lane_valid=1, lane_number=0x1a,
                n_fts=255,
                rate_gen1=1,
                **{ctrl:1})

    @simulation_test
    def test_rx_ts1_ctrl_invalid(self, tb):
        yield from self.tb.transmit([
            K(28,5), K(23,7), K(23,7), 0xff, 0b0010, 0x1ee
        ])
        yield from self.assertError(tb)

    @simulation_test
    def test_rx_ts1_idN_invalid(self, tb):
        for n in range(10):
            yield self.tb.lane.rx_symbol.eq(0)
            yield
            yield from self.tb.transmit([
                K(28,5), 0xaa, 0x1a, 0xff, 0b0010, 0b0001, *[D(10,2) for _ in range(n)], 0x1ee
            ])
            yield from self.assertError(tb)

    @simulation_test
    def test_rx_ts1_2x_same_valid(self, tb):
        yield from self.tb.transmit([
            K(28,5), 0xaa, 0x1a, 0xff, 0b0010, 0b0000, *[D(10,2) for _ in range(10)],
            K(28,5), 0xaa, 0x1a, 0xff, 0b0010, 0b0000, *[D(10,2) for _ in range(10)],
            K(28,5)
        ])
        yield from self.assertSignal(tb.phy.ts.valid, 1)

    @simulation_test
    def test_rx_ts1_2x_different_invalid(self, tb):
        yield from self.tb.transmit([
            K(28,5), 0xaa, 0x1a, 0xff, 0b0010, 0b0000, *[D(10,2) for _ in range(10)],
            K(28,5), 0xaa, 0x1a, 0xff, 0b0010, 0b0001, *[D(10,2) for _ in range(10)],
            K(28,5)
        ])
        yield from self.assertSignal(tb.phy.ts.valid, 0)

    @simulation_test
    def test_rx_ts1_3x_same_different_invalid(self, tb):
        yield from self.tb.transmit([
            K(28,5), 0xaa, 0x1a, 0xff, 0b0010, 0b0000, *[D(10,2) for _ in range(10)],
            K(28,5), 0xaa, 0x1a, 0xff, 0b0010, 0b0000, *[D(10,2) for _ in range(10)],
            K(28,5), 0xaa, 0x1a, 0xff, 0b0010, 0b0001, *[D(10,2) for _ in range(10)],
            K(28,5)
        ])
        yield from self.assertSignal(tb.phy.ts.valid, 0)

    @simulation_test
    def test_rx_ts1_3x_same_different_invalid(self, tb):
        yield from self.tb.transmit([
            K(28,5), 0xaa, 0x1a, 0xff, 0b0010, 0b0000, *[D(10,2) for _ in range(10)],
            K(28,5), 0xaa, 0x1a, 0xff, 0b0010, 0b0000, *[D(10,2) for _ in range(10)],
            K(28,5), 0xaa, 0x1a, 0xff, 0b0010, 0b0001, *[D(10,2) for _ in range(10)],
            K(28,5)
        ])
        yield from self.assertSignal(tb.phy.ts.valid, 0)

    @simulation_test
    def test_rx_ts1_skp_ts1_valid(self, tb):
        yield from self.tb.transmit([
            K(28,5), 0xaa, 0x1a, 0xff, 0b0010, 0b0000, *[D(10,2) for _ in range(10)],
            K(28,5), K(28,0), K(28,0), K(28,0),
            K(28,5), 0xaa, 0x1a, 0xff, 0b0010, 0b0000, *[D(10,2) for _ in range(10)],
            K(28,5)
        ])
        yield from self.assertSignal(tb.phy.ts.valid, 1)


class PCIePHYRXGear2xTestCase(_PCIePHYRXTestCase):
    def setUp(self):
        self.tb = PCIePHYRXTestbench(ratio=2)

    def simulationSetUp(self, tb):
        yield tb.lane.rx_valid.eq(1)

    @simulation_test
    def test_rx_ts1_2x_same_valid(self, tb):
        yield from self.tb.transmit([
            (K(28,5), 0xaa), (0x1a, 0xff), (0b0010, 0b0000),
                *[(D(10,2), D(10,2)) for _ in range(5)],
            (K(28,5), 0xaa), (0x1a, 0xff), (0b0010, 0b0000),
                *[(D(10,2), D(10,2)) for _ in range(5)],
            (K(28,5), K(28,0)),
        ])
        yield from self.assertSignal(tb.phy.ts.valid, 1)
