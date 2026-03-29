from extractors.nds import NdsExtractor
from extractors.wii import WiiExtractor
from extractors.n3ds import N3dsExtractor
from extractors.psp import PspExtractor

# Maps file extension -> list of extractor classes to try in order.
# The first one to return a non-None result wins.
EXTRACTOR_MAP = {
    '.nds': [NdsExtractor],
    '.dsi': [NdsExtractor],
    '.iso': [WiiExtractor, PspExtractor],
    '.wbfs': [WiiExtractor],
    '.wia': [WiiExtractor],
    '.3ds': [N3dsExtractor],
    '.cci': [N3dsExtractor],
    '.cia': [N3dsExtractor],
    '.pbp': [PspExtractor],
    '.cso': [PspExtractor],
}
