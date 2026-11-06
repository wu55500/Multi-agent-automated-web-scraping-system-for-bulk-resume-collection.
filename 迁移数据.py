"""Safe replacement for legacy whole-table-skip migration. Original DB remains unchanged.
Usage: python3 迁移数据.py --root var/tenants --tenant personal migrate-legacy --db dz.db --consent owned-export
"""
from dz.platform.cli import main
if __name__ == '__main__':
    raise SystemExit(main())
