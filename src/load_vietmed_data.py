# convert_vietmed_ner.py
from datasets import load_dataset
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(ROOT_DIR, "data")


def write_bio_file(dataset, split_name, output_path):
    """
    Viết file theo format CoNLL:
    word label
    word label
    ...
    (dòng trống giữa các câu)
    """
    data = dataset[split_name]

    with open(output_path, "w", encoding="utf-8") as f:
        for example in data:
            words = example["words"]  # list các từ
            labels = example["labels"]  # list BIO labels (đã là string)

            # Đảm bảo độ dài khớp
            if len(words) != len(labels):
                print(f"Cảnh báo: độ dài không khớp ở mẫu {example.get('text', '')[:50]}")
                continue

            for word, label in zip(words, labels):
                # Một số mẫu dùng "0" thay vì "O"
                if label == "0":
                    label = "O"
                f.write(f"{word} {label}\n")
            f.write("\n")  # dòng trống ngăn cách câu

    print(f"✅ Đã lưu {len(data)} mẫu vào {output_path}")


def create_labels(dataset):
    all_labels = set()

    for split in dataset:
        for example in dataset[split]:
            for label in example["labels"]:
                if label == "0":
                    label = "O"
                all_labels.add(label)

    # Sắp xếp: O trước, rồi B-, I-
    sorted_labels = sorted(all_labels, key=lambda x: (x != "O", x))
    labels_path = os.path.join(DATA_DIR, "labels.txt")
    with open(labels_path, "w", encoding="utf-8") as f:
        for lab in sorted_labels:
            f.write(lab + "\n")

    print("Các label:", sorted_labels)
    print(f"✅ Đã lưu {labels_path}")


def export_to_files(dataset):
    os.makedirs(DATA_DIR, exist_ok=True)
    train_path = os.path.join(DATA_DIR, "train.txt")
    dev_path = os.path.join(DATA_DIR, "dev.txt")

    # Xuất file
    write_bio_file(dataset, "train", train_path)

    # Nếu có validation / test
    if "validation" in dataset:
        write_bio_file(dataset, "validation", dev_path)
    elif "test" in dataset:
        write_bio_file(dataset, "test", dev_path)
    else:
        # Nếu chỉ có train thì tách 10% làm dev
        print("Không có validation, đang tách 10% từ train làm dev...")
        split = dataset["train"].train_test_split(test_size=0.1, seed=42)
        # Ghi lại train và dev
        with open(train_path, "w", encoding="utf-8") as f:
            for example in split["train"]:
                for word, label in zip(example["words"], example["labels"]):
                    if label == "0":
                        label = "O"
                    f.write(f"{word} {label}\n")
                f.write("\n")
        with open(dev_path, "w", encoding="utf-8") as f:
            for example in split["test"]:
                for word, label in zip(example["words"], example["labels"]):
                    if label == "0":
                        label = "O"
                    f.write(f"{word} {label}\n")
                f.write("\n")
        print("✅ Đã tách train/dev")

    print(f"\nHoàn tất! Bạn có thể dùng {train_path} và {dev_path} để train.")


def main():
    # Windows consoles often default to cp1252; force UTF-8 for Vietnamese text.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("Loading VietMed-NER...")
    # Audio decoding needs torchcodec + FFmpeg shared DLLs on Windows.
    # This script only exports text NER fields, so drop audio entirely.
    dataset = load_dataset("leduckhai/VietMed-NER")
    dataset = dataset.remove_columns(
        [c for c in ("audio", "duration") if c in dataset["train"].column_names]
    )

    print(dataset)  # xem cấu trúc
    print(dataset["train"][0])  # xem 1 mẫu

    export_to_files(dataset)
    create_labels(dataset)


if __name__ == "__main__":
    main()
