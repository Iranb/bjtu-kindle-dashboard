package kcalendar

import (
	"bytes"
	"context"
	"crypto/tls"
	"embed"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
	"unicode"

	"github.com/6tail/lunar-go/calendar"
)

//go:embed data/*.json
var builtInHolidayData embed.FS

const holidayURL = "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/%d.json"

type HolidayDay struct {
	Name     string `json:"name"`
	Date     string `json:"date"`
	IsOffDay bool   `json:"isOffDay"`
}

type HolidayYear struct {
	Schema string       `json:"$schema,omitempty"`
	ID     string       `json:"$id,omitempty"`
	Year   int          `json:"year"`
	Papers []string     `json:"papers,omitempty"`
	Days   []HolidayDay `json:"days"`
}

type DayInfo struct {
	LunarLabel  string
	HolidayName string
	IsOffDay    bool
	IsWorkday   bool
}

type HolidayRefreshResult struct {
	Updated, NotModified, Failed int
}

func hasUnsafeText(s string) bool {
	if len([]rune(s)) > 32 || strings.TrimSpace(s) != s || s == "" {
		return true
	}
	for _, r := range s {
		if unicode.IsControl(r) {
			return true
		}
	}
	return false
}

func ParseHolidayYear(data []byte, expectedYear int) (HolidayYear, error) {
	var h HolidayYear
	decoder := json.NewDecoder(strings.NewReader(string(data)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&h); err != nil {
		return h, fmt.Errorf("invalid holiday JSON")
	}
	var trailing any
	if err := decoder.Decode(&trailing); err != io.EOF {
		return h, fmt.Errorf("invalid trailing holiday JSON")
	}
	if h.Year != expectedYear || len(h.Days) > 128 {
		return h, fmt.Errorf("holiday year mismatch or item limit exceeded")
	}
	seen := map[string]bool{}
	for _, day := range h.Days {
		date, err := time.Parse("2006-01-02", day.Date)
		if err != nil || date.Year() != expectedYear || hasUnsafeText(day.Name) || seen[day.Date] {
			return h, fmt.Errorf("invalid holiday day")
		}
		seen[day.Date] = true
	}
	return h, nil
}

func loadHolidayYear(stateDir string, year int) (HolidayYear, error) {
	if stateDir != "" {
		if data, err := os.ReadFile(filepath.Join(stateDir, fmt.Sprintf("%d.json", year))); err == nil {
			if parsed, err := ParseHolidayYear(data, year); err == nil {
				return parsed, nil
			}
		}
	}
	data, err := builtInHolidayData.ReadFile(fmt.Sprintf("data/%d.json", year))
	if err != nil {
		return HolidayYear{Year: year}, nil
	}
	return ParseHolidayYear(data, year)
}

func holidayMap(stateDir string, from, to time.Time) (map[string]HolidayDay, error) {
	out := map[string]HolidayDay{}
	for year := from.Year(); year <= to.Year(); year++ {
		holidays, err := loadHolidayYear(stateDir, year)
		if err != nil {
			return nil, err
		}
		for _, day := range holidays.Days {
			out[day.Date] = day
		}
	}
	return out, nil
}

func lunarLabel(day time.Time) string {
	lunar := calendar.NewSolarFromYmd(day.Year(), int(day.Month()), day.Day()).GetLunar()
	if jieQi := lunar.GetJieQi(); jieQi != "" {
		return jieQi
	}
	if lunar.GetDay() == 1 {
		return lunar.GetMonthInChinese() + "月"
	}
	return lunar.GetDayInChinese()
}

func BuildDayInfo(stateDir string, from, to time.Time) (map[string]DayInfo, error) {
	holidays, err := holidayMap(stateDir, from, to)
	if err != nil {
		return nil, err
	}
	out := map[string]DayInfo{}
	for day := from; day.Before(to); day = day.AddDate(0, 0, 1) {
		key := dayKey(day)
		info := DayInfo{LunarLabel: lunarLabel(day)}
		if holiday, ok := holidays[key]; ok {
			info.HolidayName = holiday.Name
			info.IsOffDay = holiday.IsOffDay
			info.IsWorkday = !holiday.IsOffDay
		}
		out[key] = info
	}
	return out, nil
}

func HolidayRefreshDue(stateDir string, now time.Time, interval time.Duration) bool {
	info, err := os.Stat(filepath.Join(stateDir, "last-holiday-refresh"))
	return err != nil || now.Sub(info.ModTime()) >= interval
}

func refreshOneHolidayYear(ctx context.Context, client *http.Client, stateDir string, year int) (string, error) {
	metadataPath := filepath.Join(stateDir, fmt.Sprintf("%d.http.json", year))
	m := loadMetadata(metadataPath)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, fmt.Sprintf(holidayURL, year), nil)
	if err != nil {
		return "", fmt.Errorf("holiday request setup failed")
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", "kindle-calendar/1")
	if m.ETag != "" {
		req.Header.Set("If-None-Match", m.ETag)
	}
	if m.LastModified != "" {
		req.Header.Set("If-Modified-Since", m.LastModified)
	}
	resp, err := client.Do(req)
	if err != nil {
		return "", fmt.Errorf("holiday download failed")
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotModified {
		return "not-modified", nil
	}
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("holiday HTTP status %d", resp.StatusCode)
	}
	contentType := strings.ToLower(strings.Split(resp.Header.Get("Content-Type"), ";")[0])
	if contentType != "application/json" && contentType != "text/plain" && contentType != "application/octet-stream" {
		return "", fmt.Errorf("unexpected holiday content type")
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, (128<<10)+1))
	if err != nil || len(data) > 128<<10 {
		return "", fmt.Errorf("holiday body invalid or too large")
	}
	if _, err := ParseHolidayYear(data, year); err != nil {
		return "", err
	}
	if err := atomicWrite(filepath.Join(stateDir, fmt.Sprintf("%d.json", year)), data, 0600); err != nil {
		return "", fmt.Errorf("holiday cache write failed")
	}
	etag := resp.Header.Get("ETag")
	lastModified := resp.Header.Get("Last-Modified")
	if len(etag) > 256 || strings.ContainsAny(etag, "\r\n") {
		etag = ""
	}
	if len(lastModified) > 128 || strings.ContainsAny(lastModified, "\r\n") {
		lastModified = ""
	}
	m = metadata{ETag: etag, LastModified: lastModified}
	meta, _ := json.Marshal(m)
	if err := atomicWrite(metadataPath, append(meta, '\n'), 0600); err != nil {
		return "", fmt.Errorf("holiday metadata write failed")
	}
	return "updated", nil
}

// RefreshHolidays is best-effort: callers should still render from the bundled
// or last-known-good data when one or both network requests fail.
func RefreshHolidays(ctx context.Context, stateDir string, now time.Time, timeout time.Duration) HolidayRefreshResult {
	client := &http.Client{
		Timeout:   timeout,
		Transport: &http.Transport{TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12}},
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= 3 || req.URL.Scheme != "https" {
				return fmt.Errorf("unsafe holiday redirect")
			}
			return nil
		},
	}
	result := HolidayRefreshResult{}
	for _, year := range []int{now.Year(), now.Year() + 1} {
		status, err := refreshOneHolidayYear(ctx, client, stateDir, year)
		if err != nil {
			result.Failed++
			continue
		}
		if status == "updated" {
			result.Updated++
		} else {
			result.NotModified++
		}
	}
	if result.Failed == 0 {
		_ = atomicWrite(filepath.Join(stateDir, "last-holiday-refresh"), []byte(now.Format(time.RFC3339)+"\n"), 0600)
	}
	return result
}

func NextDailyRefresh(now time.Time, hour, minute int) time.Time {
	loc := now.Location()
	next := time.Date(now.Year(), now.Month(), now.Day(), hour, minute, 0, 0, loc)
	if !next.After(now) {
		next = next.AddDate(0, 0, 1)
	}
	return next
}

func RenderOfflineToFile(output, holidayStateDir string, opts RenderOptions) error {
	if opts.Location == nil {
		opts.Location = time.Local
	}
	now := opts.Now.In(opts.Location)
	gridStart := monthGridStart(now)
	gridEnd := gridStart.AddDate(0, 0, 42)
	dayInfo, err := BuildDayInfo(holidayStateDir, gridStart, gridEnd)
	if err != nil {
		return err
	}
	opts.DayInfo = dayInfo
	var image bytes.Buffer
	if err := RenderMonth(&image, nil, opts); err != nil {
		return err
	}
	return atomicWrite(output, image.Bytes(), 0644)
}
