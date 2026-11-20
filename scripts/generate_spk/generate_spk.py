
import xml.etree.ElementTree as ET
import numpy as np

from pathlib import Path
from dataclasses import dataclass

"""Generate a Milani SPK from Milani Long Term Trajectories"""


# Paths
LTP_PATH = Path("/Users/valtterimj/Downloads/Work/Hera/milani_ltt/MILANI_CFDSOC_LongTermTraj_LTP005_01_2026-10-26T08-24-14-825.XML")
KERNELS_DIR = Path("/Users/valtterimj/Downloads/Work/Hera/hera_spice/kernels")
OUPUT_DIR = Path(__file__).parent

# Constants
STATE_KEYS = ("X", "Y", "Z", "X_DOT", "Y_DOT", "Z_DOT")

@dataclass
class Segment:
    metadata: dict # Segemnt metadata as dict
    epochs: list # Epoch string as writen in xml
    states: np.ndarray # shape (N, 6): km and km/s


def find_required(elem, tag):
    child = elem.find(tag)
    if child is None:
        raise ValueError(f"<{tag}> not found in <{elem.tag}>")
    return child

def parse_segments(seg, index):
    metadata = {
        item.tag: item.text.strip()
        for item in find_required(seg, "metadata")
        if item.tag != "COMMENT"
    }

    epochs, states = [], []
    for sv in find_required(seg, "data").findall("stateVector"):
        epochs.append(find_required(sv, "EPOCH").text.strip())
        states.append([float(find_required(sv, key).text) for key in STATE_KEYS])

    if not epochs:
        raise ValueError(f"Segment {index}: no state vectors")
    return Segment(metadata, epochs, np.array(states))

def parse_ltp(path):
    root = ET.parse(path).getroot()
    segments = find_required(root, "body").findall("segment")
    if not segments:
        raise ValueError(f"No segments found in {path}")
    return [parse_segments(seg, i) for i, seg in enumerate(segments, start=1)]

def main():
    segments = parse_ltp(LTP_PATH)
    print("Segments:", len(segments))
    print("Total states:", sum(len(s.epochs) for s in segments))
    print("First segment metadata:", segments[0].metadata)
    print("First state:", segments[0].epochs[0], segments[0].states[0])

if __name__ == "__main__":
    main()