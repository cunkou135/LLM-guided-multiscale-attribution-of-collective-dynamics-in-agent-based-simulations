"""Fetch the publisher's immutable public archive and extract one benchmark cache.

No pickle is loaded here. check_covasim_engine loads the verified publisher cache
only when explicitly requested, inside the separate Covasim environment.
"""
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen
import zipfile

ARCHIVE_SHA256 = 'e09210384c07ad57c62e5abc920163c7165b0cc6a9d5db1276b6324cac35d0ba'
CACHE_SHA256 = '8f562e6823ca38f7f4db601ee51985c2825eeaa841c9f2707c853a02bcecfa34'


def main():
    target = Path('results/reference')
    target.mkdir(parents=True, exist_ok=True)
    archive = target / 'ttq_4699175.zip'
    if not archive.exists():
        with urlopen('https://zenodo.org/api/records/4699175', timeout=60) as response:
            record = json.load(response)
        source = record['files'][0]['links']['self']
        with urlopen(source, timeout=60) as response, archive.open('wb') as stream:
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                stream.write(chunk)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA256:
        raise ValueError('Publisher archive hash differs from audited version')
    with zipfile.ZipFile(archive) as zipped:
        names = [n for n in zipped.namelist() if n.endswith('/fig3_theoretical/fig3_transtrees.obj')]
        if len(names) != 1:
            raise ValueError('Expected exactly one Figure 3 cache')
        data = zipped.read(names[0])
    if hashlib.sha256(data).hexdigest() != CACHE_SHA256:
        raise ValueError('Reference cache hash differs from audited version')
    out = target / 'fig3_transtrees.obj'
    out.write_bytes(data)
    print(out)


if __name__ == '__main__':
    main()
