package kcalendar

import (
	"bytes"
	"image"
	"image/png"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestBuiltInHolidayAndLunarAnnotations(t *testing.T) {
	loc, _ := time.LoadLocation("Asia/Shanghai")
	from := time.Date(2026, 9, 20, 0, 0, 0, 0, loc)
	info, err := BuildDayInfo(t.TempDir(), from, from.AddDate(0, 0, 8))
	if err != nil {
		t.Fatal(err)
	}
	workday := info["2026-09-20"]
	if !workday.IsWorkday || workday.IsOffDay || workday.HolidayName != "国庆节" {
		t.Fatalf("workday=%+v", workday)
	}
	holiday := info["2026-09-25"]
	if !holiday.IsOffDay || holiday.IsWorkday || holiday.HolidayName != "中秋节" {
		t.Fatalf("holiday=%+v", holiday)
	}
	if holiday.LunarLabel == "" {
		t.Fatal("lunar label is empty")
	}
}

func TestHolidayValidationRejectsWrongYearDuplicateAndControlText(t *testing.T) {
	bad := []string{
		`{"year":2025,"days":[]}`,
		`{"year":2026,"days":[{"name":"元旦","date":"2026-01-01","isOffDay":true},{"name":"元旦","date":"2026-01-01","isOffDay":true}]}`,
		"{\"year\":2026,\"days\":[{\"name\":\"bad\\nname\",\"date\":\"2026-01-01\",\"isOffDay\":true}]}",
		`{"year":2026,"days":[],"unexpected":true}`,
		`{"year":2026,"days":[]} {"year":2026,"days":[]}`,
	}
	for _, input := range bad {
		if _, err := ParseHolidayYear([]byte(input), 2026); err == nil {
			t.Fatalf("accepted invalid holiday JSON: %s", input)
		}
	}
}

func TestOfflineRenderNeedsNoFeedOrNetwork(t *testing.T) {
	dir := t.TempDir()
	loc, _ := time.LoadLocation("Asia/Shanghai")
	output := filepath.Join(dir, "calendar.png")
	err := RenderOfflineToFile(output, filepath.Join(dir, "holidays"), RenderOptions{
		Width: 600, Height: 800, Now: time.Date(2026, 9, 20, 12, 0, 0, 0, loc), Location: loc,
	})
	if err != nil {
		t.Fatal(err)
	}
	data, err := os.ReadFile(output)
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := png.Decode(bytes.NewReader(data))
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := decoded.(*image.Gray); !ok {
		t.Fatalf("image type=%T", decoded)
	}
}

func TestKindleDefaultFontListIncludesDeviceCJKFont(t *testing.T) {
	if _, err := os.Stat("../../cmd/kindle-calendar/main.go"); err != nil {
		t.Skip("source tree unavailable")
	}
	source, err := os.ReadFile("../../cmd/kindle-calendar/main.go")
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(source, []byte("/usr/java/lib/fonts/STHeitiMedium.ttf")) {
		t.Fatal("Kindle CJK fallback is missing")
	}
}

func TestNextDailyRefresh(t *testing.T) {
	loc, _ := time.LoadLocation("Asia/Shanghai")
	before := time.Date(2026, 9, 20, 0, 4, 0, 0, loc)
	if got := NextDailyRefresh(before, 0, 5); got.Day() != 20 || got.Hour() != 0 || got.Minute() != 5 {
		t.Fatalf("before: %v", got)
	}
	after := time.Date(2026, 9, 20, 0, 6, 0, 0, loc)
	if got := NextDailyRefresh(after, 0, 5); got.Day() != 21 || got.Hour() != 0 || got.Minute() != 5 {
		t.Fatalf("after: %v", got)
	}
}
