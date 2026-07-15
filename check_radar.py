import sys
import os

sys.path.append("/Users/travisbadgley/openpilot")

from openpilot.tools.lib.route import Route
from openpilot.tools.lib.logreader import LogReader
from opendbc.can.parser import CANParser

def parse_radar(route_name):
    r = Route(route_name)
    path = r.log_paths()[0]
    if path is None:
        for p in r.log_paths():
            if p is not None:
                path = p
                break
                
    lr = LogReader(path)
    
    # We want to use the honda_civic_bosch_radar DBC
    # The message ID is 0x280 (640)
    msg_name = 'RADAR_TRACK_1' # wait, 0x280 is what message? Let's check the dbc file directly
    
    import opendbc.can.parser as parser
    
    # Actually just print the hex data and we can look at the DBC.
    # The user is asking "are they implementing it correctly?"
    # What does the data look like?
    samples = set()
    for msg in lr:
        if msg.which() == 'can':
            for can_msg in msg.can:
                if can_msg.address == 0x280 and can_msg.src == 0:
                    hex_dat = can_msg.dat.hex()
                    # An empty track seems to start with fef0fff
                    # Check if it has different data (i.e., a real track)
                    if not hex_dat.startswith("fef0fff"):
                        samples.add(hex_dat)
                        if len(samples) > 20:
                            break
        if len(samples) > 20:
            break
            
    print("Unique 0x280 data payloads (first 20):")
    for s in samples:
        print(s)

if __name__ == "__main__":
    parse_radar("805f87f5e96d128c|0000003e--99e2d4950f")
