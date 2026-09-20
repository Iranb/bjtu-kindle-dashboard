package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"
	_ "time/tzdata"

	"github.com/Iranb/bjtu-kindle-dashboard/internal/kcalendar"
)

func main() {
	var mode, feed, cache, meta, output, caFile, timezone, fonts, holidayDir string
	var width, height int
	var maxBytes int64
	var timeout, holidayRefreshInterval time.Duration
	var allowHTTP bool
	var refreshHolidays, holidayOnly bool
	var dailyHour, dailyMinute int
	flag.StringVar(&mode, "mode", "offline", "calendar mode: offline or ics")
	flag.StringVar(&feed, "feed-file", "/var/local/kindle-calendar/feed.url", "0600 file containing the private ICS URL")
	flag.StringVar(&cache, "cache-file", "/var/local/kindle-calendar/calendar.ics", "private last-good ICS cache")
	flag.StringVar(&meta, "metadata-file", "/var/local/kindle-calendar/http.json", "private HTTP validator state")
	flag.StringVar(&output, "output", "/mnt/us/screensavers/kindle-calendar.png", "output grayscale PNG")
	flag.StringVar(&caFile, "ca-file", "", "optional PEM CA bundle")
	flag.StringVar(&holidayDir, "holiday-dir", "/var/local/kindle-calendar/holidays", "private holiday cache directory")
	flag.StringVar(&timezone, "timezone", "Asia/Shanghai", "IANA display timezone")
	flag.StringVar(
		&fonts,
		"fonts",
		"/usr/java/lib/fonts/DroidSansFallbackFull.ttf,/usr/java/lib/fonts/DroidSansFallback.ttf,/usr/java/lib/fonts/Helvetica_LT_65_Medium.ttf,/System/Library/Fonts/Supplemental/Arial Unicode.ttf,/Library/Fonts/Arial Unicode.ttf",
		"comma-separated font fallbacks",
	)
	flag.IntVar(&width, "width", 1072, "screen width")
	flag.IntVar(&height, "height", 1448, "screen height")
	flag.Int64Var(&maxBytes, "max-bytes", 4<<20, "maximum ICS response size")
	flag.DurationVar(&timeout, "timeout", 30*time.Second, "HTTPS request timeout")
	flag.BoolVar(&refreshHolidays, "refresh-holidays", false, "best-effort refresh of public holiday data")
	flag.BoolVar(&holidayOnly, "holiday-only", false, "refresh public holidays without rendering")
	flag.DurationVar(&holidayRefreshInterval, "holiday-refresh-interval", 7*24*time.Hour, "minimum holiday refresh interval")
	flag.IntVar(&dailyHour, "daily-hour", 0, "daily local render hour")
	flag.IntVar(&dailyMinute, "daily-minute", 5, "daily local render minute")
	flag.BoolVar(&allowHTTP, "allow-http", false, "allow HTTP (tests only)")
	flag.Parse()
	loc, err := time.LoadLocation(timezone)
	if err != nil {
		fmt.Fprintln(os.Stderr, "error: invalid timezone")
		os.Exit(2)
	}
	now := time.Now().In(loc)
	if dailyHour < 0 || dailyHour > 23 || dailyMinute < 0 || dailyMinute > 59 {
		fmt.Fprintln(os.Stderr, "error: invalid daily refresh time")
		os.Exit(2)
	}
	if mode == "offline" {
		holidayResult := kcalendar.HolidayRefreshResult{}
		holidayStatus := "skipped"
		if refreshHolidays && kcalendar.HolidayRefreshDue(holidayDir, now, holidayRefreshInterval) {
			holidayResult = kcalendar.RefreshHolidays(context.Background(), holidayDir, now, timeout)
			holidayStatus = "ok"
			if holidayResult.Failed > 0 {
				holidayStatus = "partial"
			}
		}
		if holidayOnly {
			fmt.Printf("result=ok mode=holiday-only holiday=%s updated=%d not_modified=%d failed=%d\n", holidayStatus, holidayResult.Updated, holidayResult.NotModified, holidayResult.Failed)
			return
		}
		err = kcalendar.RenderOfflineToFile(output, holidayDir, kcalendar.RenderOptions{
			Width: width, Height: height, Now: now, Location: loc, FontPaths: strings.Split(fonts, ","),
		})
		if err != nil {
			fmt.Fprintf(os.Stderr, "error: offline render failed: %v\n", err)
			os.Exit(1)
		}
		nextDue := kcalendar.NextDailyRefresh(now, dailyHour, dailyMinute).Unix()
		fmt.Printf("result=ok mode=offline holiday=%s updated=%d not_modified=%d failed=%d next_due=%d\n", holidayStatus, holidayResult.Updated, holidayResult.NotModified, holidayResult.Failed, nextDue)
		return
	}
	if mode != "ics" {
		fmt.Fprintln(os.Stderr, "error: mode must be offline or ics")
		os.Exit(2)
	}
	result, err := kcalendar.Update(context.Background(), kcalendar.UpdateOptions{
		FeedFile: feed, CacheFile: cache, MetadataFile: meta, OutputFile: output,
		CAFile: caFile, Location: loc, Now: now, Width: width, Height: height,
		FontPaths: strings.Split(fonts, ","), MaxBytes: maxBytes, Timeout: timeout, AllowHTTP: allowHTTP,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
	fmt.Printf("result=ok http=%d not_modified=%t events=%d\n", result.HTTPStatus, result.NotModified, result.EventCount)
}
