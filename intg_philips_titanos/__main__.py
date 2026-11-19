"""Entry point: `python -m intg_philips_titanos`, and the PyInstaller executable."""

import asyncio

from intg_philips_titanos.runtime import main

if __name__ == "__main__":
    asyncio.run(main())
