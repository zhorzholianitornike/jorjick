---
name: card-generate
description: Generate a test news card locally using card_generator.py. Use when you want to test card rendering with a sample photo, name, and text without uploading to Facebook.
disable-model-invocation: true
allowed-tools: Bash(python3 *)
argument-hint: [photo_path] [name] [text]
---

# Card Generate — Local Test

Generate a news card locally for testing the card design.

## Usage

```
/card-generate photo.jpg "Name Surname" "News headline or description text"
```

Arguments via `$ARGUMENTS`:
- `$ARGUMENTS[0]` — path to the photo (must exist in the project dir or temp/)
- `$ARGUMENTS[1]` — name/surname (will be uppercased on the card)
- `$ARGUMENTS[2]` — description text (displayed as-is)

## Steps

1. Verify the photo file exists. If not, list files in `temp/` and `uploads/` to find available photos.
2. Run the generator:

```bash
cd "/Users/toko/Documents/VC Code"
python3 -c "
from card_generator import CardGenerator
gen = CardGenerator()
out = gen.generate('$ARGUMENTS[0]', '$ARGUMENTS[1]', '$ARGUMENTS[2]', 'temp/test_card.jpg')
print(f'Card saved: {out}')
"
```

3. Confirm the output file exists and report the path.

## Notes

- Output goes to `temp/test_card.jpg`
- Logo is optional — pass `logo_path` to CardGenerator() if you have one
- Card size: 1080×1350 portrait JPEG, quality 95
- The diagonal overlay, red square prefix, gradient separator line, and bottom bar are all handled automatically by card_generator.py
