import argparse
from pathlib import Path

import cv2
import numpy as np


def merge_ranges(ranges, gap=6):
    merged = []
    for start, end in ranges:
        if not merged or start - merged[-1][1] > gap:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def detect_options(image):
    # White story options in the middle of the screen.
    lower = np.array([235, 235, 235], dtype=np.uint8)
    upper = np.array([255, 255, 255], dtype=np.uint8)
    mask = cv2.inRange(image, lower, upper)

    height, width = mask.shape
    # Keep the central story area, avoiding top HUD and bottom dialog text.
    roi = mask[int(height * 0.16):int(height * 0.78), int(width * 0.15):int(width * 0.85)]
    y_offset = int(height * 0.16)
    x_offset = int(width * 0.15)

    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 5))
    roi = cv2.morphologyEx(roi, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        x1, y1, x2, y2 = x + x_offset, y + y_offset, x + x_offset + w, y + y_offset + h
        area = w * h
        if area < 10000:
            continue
        if w < width * 0.35 or h < 25:
            continue
        boxes.append((x1, y1, x2, y2))

    boxes = sorted(boxes, key=lambda box: box[1])
    return boxes


def main():
    parser = argparse.ArgumentParser(description='Detect story option button coordinates from a screenshot.')
    parser.add_argument('image', type=Path, help='Screenshot path')
    parser.add_argument('--annotate', type=Path, help='Optional output path for an annotated image')
    args = parser.parse_args()

    image = cv2.imread(str(args.image))
    if image is None:
        raise SystemExit(f'Failed to read image: {args.image}')

    boxes = detect_options(image)
    if not boxes:
        raise SystemExit('No story options detected')

    print(f'Detected {len(boxes)} options')
    for index, (x1, y1, x2, y2) in enumerate(boxes, start=1):
        cx = (x1 + x2) // 2
        cy = (y1 + y2) // 2
        print(f'{index}: area=({x1}, {y1}, {x2}, {y2}), center=({cx}, {cy})')

    x1 = min(box[0] for box in boxes)
    y1 = min(box[1] for box in boxes)
    x2 = max(box[2] for box in boxes)
    y2 = max(box[3] for box in boxes)
    print(f'story_option_area=({x1}, {y1}, {x2}, {y2})')
    print(f'click_4th_center=({(boxes[3][0] + boxes[3][2]) // 2}, {(boxes[3][1] + boxes[3][3]) // 2})' if len(boxes) >= 4 else 'click_4th_center=N/A')

    if args.annotate:
        annotated = image.copy()
        for index, (x1, y1, x2, y2) in enumerate(boxes, start=1):
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
            cv2.putText(annotated, str(index), (x1 + 8, y1 + 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
        cv2.imwrite(str(args.annotate), annotated)


if __name__ == '__main__':
    main()
