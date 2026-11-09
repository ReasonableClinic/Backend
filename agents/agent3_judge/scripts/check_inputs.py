"""받은 zip 4개(for_agent3_v10, agent3_kit_v14_9, agent3_test_kit_v14_9, agent2_v14_13의 dev 근거 v14.12)와 지금 폴더의 파일이 같은지 확인.

  python3 scripts/check_inputs.py [zip 폴더 (기본: agent3_final의 상위 폴더)]

zip 안 파일이 하나라도 없거나 다르면 종료 코드 1. agent3_kit/·data/에 zip에 없는 파일(예전 판)이 남아 있어도 1.
"""
import hashlib
import os
import sys
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# zip 안 경로 접두어 -> 이 폴더 안 위치. 문서·도구는 docs/, tools/로 옮겨 둠
ZIPS = {
    "for_agent3_v10.zip": [("for_agent3_v10/dev/", "data/dev/"), ("for_agent3_v10/test/", "data/test/"),
                           ("for_agent3_v10/", "docs/")],
    "agent3_kit_v14_9.zip": [("agent3_kit/", "agent3_kit/"), ("agent2/", "agent2/"), ("code/", "tools/"), ("", "docs/")],
    "agent3_test_kit_v14_9.zip": [("agent3_kit/", "agent3_kit/"), ("", "docs/")],
    # a3-0.3.1: dev 근거 v14.12만 가져옴 (Agent 2 노션 "agent 2" 항목의 zip)
    "agent2_v14_13.zip": [("agent3_kit/evidence_dev_haiku_v14_12", "agent3_kit/evidence_dev_haiku_v14_12"),
                          ("agent3_kit/evidence_dev_variants_haiku_v14_12", "agent3_kit/evidence_dev_variants_haiku_v14_12")],
}
# 이름을 바꿔 둔 파일
RENAME = {"for_agent3_v10/README.md": "docs/DATA_README_v10.md"}


def sha(b):
    return hashlib.sha256(b).hexdigest()


def main():
    zdir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(HERE)
    bad, expected = 0, set()
    for name, rules in ZIPS.items():
        zpath = os.path.join(zdir, name)
        if not os.path.exists(zpath):
            print(f"[없음] {zpath}")
            bad += 1
            continue
        z = zipfile.ZipFile(zpath)
        same = 0
        for info in z.infolist():
            if info.is_dir():
                continue
            local = RENAME.get(info.filename)
            if local is None:
                match = next(((s, d) for s, d in rules if info.filename.startswith(s)), None)
                if match is None:               # 이 zip에서 가져오지 않는 파일
                    continue
                src, dst = match
                local = dst + info.filename[len(src):]   # dst는 "폴더/" 또는 파일 이름 앞부분
            expected.add(os.path.normpath(local))
            path = os.path.join(HERE, local)
            if not os.path.exists(path):
                print(f"[빠짐] {local}  ({name})")
                bad += 1
            elif sha(open(path, "rb").read()) != sha(z.read(info)):
                print(f"[다름] {local}  ({name})")
                bad += 1
            else:
                same += 1
        print(f"{name}: 같음 {same}")
    # 예전 판이 섞여 있는지: agent3_kit/·data/ 안에 zip에 없는 파일
    for top in ("agent3_kit", "data"):
        for root, _, files in os.walk(os.path.join(HERE, top)):
            for f in files:
                rel = os.path.normpath(os.path.relpath(os.path.join(root, f), HERE))
                if rel not in expected:
                    print(f"[예전 파일?] {rel}")
                    bad += 1
    print("OK: 받은 파일과 모두 같음" if bad == 0 else f"문제 {bad}건")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
