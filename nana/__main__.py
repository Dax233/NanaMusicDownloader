"""支持 python -m nana 调用。"""

from .cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
