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
	var feed, cache, meta, output, caFile, timezone, fonts string
	var width, height int
	var maxBytes int64
	var timeout time.Duration
	var allowHTTP bool
	flag.StringVar(&feed, "feed-file", "/var/local/kindle-calendar/feed.url", "0600 file containing the private ICS URL")
	flag.StringVar(&cache, "cache-file", "/var/local/kindle-calendar/calendar.ics", "private last-good ICS cache")
	flag.StringVar(&meta, "metadata-file", "/var/local/kindle-calendar/http.json", "private HTTP validator state")
	flag.StringVar(&output, "output", "/mnt/us/screensavers/kindle-calendar.png", "output grayscale PNG")
	flag.StringVar(&caFile, "ca-file", "", "optional PEM CA bundle")
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
	flag.BoolVar(&allowHTTP, "allow-http", false, "allow HTTP (tests only)")
	flag.Parse()
	loc, err := time.LoadLocation(timezone)
	if err != nil {
		fmt.Fprintln(os.Stderr, "error: invalid timezone")
		os.Exit(2)
	}
	result, err := kcalendar.Update(context.Background(), kcalendar.UpdateOptions{
		FeedFile: feed, CacheFile: cache, MetadataFile: meta, OutputFile: output,
		CAFile: caFile, Location: loc, Now: time.Now(), Width: width, Height: height,
		FontPaths: strings.Split(fonts, ","), MaxBytes: maxBytes, Timeout: timeout, AllowHTTP: allowHTTP,
	})
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
	fmt.Printf("result=ok http=%d not_modified=%t events=%d\n", result.HTTPStatus, result.NotModified, result.EventCount)
}
