from nethunter_rf.analysis import (Analyzer, Packet, Signature, hamming_bits, shannon_entropy, sparkline,
                                   timing_stats)


def pkt(n, data, ts_ms, rssi=-70.0, mod="ASK/OOK", f=433_920_000, crc=True):
    return Packet(n=n, ts_us=int(ts_ms * 1000), frequency_hz=f, modulation=mod, data=bytes.fromhex(data),
                  rssi_dbm=rssi, lqi=10, crc_ok=crc)


def test_entropy_and_hamming():
    assert shannon_entropy(b"\x00" * 10) == 0
    assert abs(shannon_entropy(bytes(range(256))) - 8) < 1e-9
    assert hamming_bits(b"\x00", b"\xff") == 8
    assert hamming_bits(b"\x00", b"\x00\x00") == 8


def test_signature_matching():
    a = Analyzer([Signature("demo", prefix="ABCD", lengths=[3], bands_mhz=[[433, 435]])])
    assert a.add_packet(pkt(1, "ABCD01", 0)).protocol == "demo"
    assert a.add_packet(pkt(2, "ABCD0102", 1)).protocol == "unknown"
    assert a.add_packet(pkt(3, "ABCD01", 2, f=868_000_000)).protocol == "unknown"


def test_builtin_test_pattern_identified():
    a = Analyzer()
    p = a.add_packet(pkt(1, b"RFB-TEST-000".hex(), 0))
    assert p.protocol == "RFB lab test pattern"


def test_classification_and_repeats():
    a = Analyzer(signatures=[])
    for i in range(5):
        a.add_packet(pkt(i, "11223344", i * 100))
    assert a.packets[-1].classification == "repeating-fixed"
    assert a.add_packet(pkt(9, "11223345", 600)).classification == "repeating-variable"
    noise = bytes(range(0, 250, 17)).hex()
    assert a.add_packet(pkt(10, noise, 700)).classification.startswith("high-entropy")
    assert a.add_packet(pkt(11, "00FF00", 800)).classification.startswith("degenerate")
    assert a.add_packet(pkt(12, "0102", 900, crc=False)).classification == "crc-failed"
    rep = a.repeated()
    assert rep[0]["count"] == 5 and rep[0]["timing"]["periodic"] is True
    vf = a.variable_fields(4)
    assert vf["variable"] == [3] and vf["constant"] == [0, 1, 2]


def test_compare():
    a = Analyzer(signatures=[])
    p1 = a.add_packet(pkt(1, "AABB", 0))
    p2 = a.add_packet(pkt(2, "AABC", 50))
    c = a.compare(p1, p2)
    assert c["diff_byte_positions"] == [1] and c["dt_ms"] == 50 and not c["identical"]


def test_timing_and_sparkline():
    t = timing_stats([0, 1000, 2000, 3000])
    assert t["mean_ms"] == 1.0 and t["periodic"]
    assert timing_stats([5]) == {"intervals": 0}
    assert len(sparkline([-100, -50, -20], width=10)) == 3


def test_summary_states_not_sdr():
    a = Analyzer()
    assert "not" in a.summary()["note"].lower() or "no raw" in a.summary()["note"].lower()
