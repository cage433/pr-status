import datetime
import os
import sys
import tempfile

from .pr_number import PRNumber


class Marks:
    def __init__(self, path: str) -> None:
        self.path = path
        self._data: dict[PRNumber, str] = {}
        if os.path.isfile(path):
            with open(path) as f:
                for line in f:
                    parts = line.strip().split(",", 1)
                    if len(parts) == 2:
                        try:
                            self._data[PRNumber(int(parts[0]))] = parts[1].strip()
                        except ValueError:
                            pass

    def get(self, pr_num: PRNumber) -> str:
        return self._data.get(pr_num, "")

    def mark(self, pr_num: PRNumber) -> None:
        timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        lines: list[str] = []
        if os.path.isfile(self.path):
            with open(self.path) as f:
                lines = [l for l in f if not l.startswith("%d," % pr_num)]
        lines.append("%d,%s\n" % (pr_num, timestamp))
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=os.path.dirname(self.path), delete=False) as tmp:
            tmp.writelines(lines)
            tmp_name = tmp.name
        os.replace(tmp_name, self.path)
        self._data[pr_num] = timestamp
        print("Marked PR #%d at %s" % (pr_num, timestamp))

    def unmark(self, pr_num: PRNumber) -> None:
        if not os.path.isfile(self.path):
            print("PR #%d is not marked" % pr_num, file=sys.stderr)
            return
        with open(self.path) as f:
            lines = f.readlines()
        new_lines = [l for l in lines if not l.startswith("%d," % pr_num)]
        if len(new_lines) == len(lines):
            print("PR #%d is not marked" % pr_num, file=sys.stderr)
            return
        with tempfile.NamedTemporaryFile("w", dir=os.path.dirname(self.path), delete=False) as tmp:
            tmp.writelines(new_lines)
            tmp_name = tmp.name
        os.replace(tmp_name, self.path)
        self._data.pop(pr_num, None)
        print("Unmarked PR #%d" % pr_num)
