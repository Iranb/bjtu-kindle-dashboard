package kcalendar

import (
	"context"
	"image"
	"image/png"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

func writeFeedFile(t *testing.T, dir, rawURL string, perm os.FileMode) string {
	t.Helper()
	path := filepath.Join(dir, "feed.url")
	if err := os.WriteFile(path, []byte(rawURL+"\n"), perm); err != nil {
		t.Fatal(err)
	}
	return path
}

func updateOpts(dir, feed string) UpdateOptions {
	loc, _ := time.LoadLocation("Asia/Shanghai")
	return UpdateOptions{
		FeedFile: feed, CacheFile: filepath.Join(dir, "calendar.ics"), MetadataFile: filepath.Join(dir, "http.json"),
		OutputFile: filepath.Join(dir, "calendar.png"), Location: loc,
		Now: time.Date(2026, 8, 18, 12, 0, 0, 0, loc), Width: 600, Height: 800,
		AllowHTTP: true, Timeout: 2 * time.Second,
	}
}

func TestUpdateETagGrayscaleAndAtomicPreservation(t *testing.T) {
	var requests atomic.Int32
	invalid := atomic.Bool{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests.Add(1)
		if r.Header.Get("If-None-Match") == `"v1"` && !invalid.Load() {
			w.WriteHeader(http.StatusNotModified)
			return
		}
		if invalid.Load() {
			w.Header().Set("Content-Type", "text/calendar")
			_, _ = w.Write([]byte("not a calendar"))
			return
		}
		w.Header().Set("Content-Type", "text/calendar; charset=utf-8")
		w.Header().Set("ETag", `"v1"`)
		_, _ = w.Write([]byte(sampleICS))
	}))
	defer server.Close()
	dir := t.TempDir()
	feed := writeFeedFile(t, dir, server.URL, 0600)
	opts := updateOpts(dir, feed)
	first, err := Update(context.Background(), opts)
	if err != nil {
		t.Fatal(err)
	}
	if first.HTTPStatus != 200 || first.NotModified {
		t.Fatalf("first=%+v", first)
	}
	file, err := os.Open(opts.OutputFile)
	if err != nil {
		t.Fatal(err)
	}
	img, err := png.Decode(file)
	file.Close()
	if err != nil {
		t.Fatal(err)
	}
	if img.Bounds().Dx() != 600 || img.Bounds().Dy() != 800 {
		t.Fatalf("bounds=%v", img.Bounds())
	}
	if _, ok := img.(*image.Gray); !ok {
		t.Fatalf("decoded image type=%T, want 8-bit grayscale", img)
	}
	before, _ := os.ReadFile(opts.OutputFile)
	second, err := Update(context.Background(), opts)
	if err != nil {
		t.Fatal(err)
	}
	if second.HTTPStatus != 304 || !second.NotModified {
		t.Fatalf("second=%+v", second)
	}
	invalid.Store(true)
	// Clear validators so the server sends the invalid body.
	if err := os.WriteFile(opts.MetadataFile, []byte("{}\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := Update(context.Background(), opts); err == nil {
		t.Fatal("invalid body should fail")
	}
	after, _ := os.ReadFile(opts.OutputFile)
	if string(before) != string(after) {
		t.Fatal("last-good image was replaced on failure")
	}
	if requests.Load() != 3 {
		t.Fatalf("requests=%d", requests.Load())
	}
}

func TestRejectInsecureFeedFileAndURL(t *testing.T) {
	dir := t.TempDir()
	feed := writeFeedFile(t, dir, "https://example.invalid/private.ics", 0644)
	_, err := Update(context.Background(), updateOpts(dir, feed))
	if err == nil || !strings.Contains(err.Error(), "permissions") {
		t.Fatalf("err=%v", err)
	}
	if err := os.Chmod(feed, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(feed, []byte("http://example.invalid/private.ics\n"), 0600); err != nil {
		t.Fatal(err)
	}
	opts := updateOpts(dir, feed)
	opts.AllowHTTP = false
	_, err = Update(context.Background(), opts)
	if err == nil || !strings.Contains(err.Error(), "HTTPS") {
		t.Fatalf("err=%v", err)
	}
}
