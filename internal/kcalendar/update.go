package kcalendar

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

type UpdateOptions struct {
	FeedFile, CacheFile, MetadataFile, OutputFile string
	CAFile                                        string
	Location                                      *time.Location
	Now                                           time.Time
	Width, Height                                 int
	FontPaths                                     []string
	MaxBytes                                      int64
	Timeout                                       time.Duration
	AllowHTTP                                     bool
	Client                                        *http.Client
}

type UpdateResult struct {
	HTTPStatus  int
	NotModified bool
	EventCount  int
}

type metadata struct {
	ETag         string `json:"etag,omitempty"`
	LastModified string `json:"last_modified,omitempty"`
}

func readSecretURL(path string, allowHTTP bool) (*url.URL, error) {
	info, err := os.Stat(path)
	if err != nil {
		return nil, fmt.Errorf("feed config unavailable")
	}
	if info.Mode().Perm()&0077 != 0 {
		return nil, fmt.Errorf("feed config permissions must be 0600")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("feed config unreadable")
	}
	raw := strings.TrimSpace(string(data))
	if strings.HasPrefix(raw, "webcal://") {
		raw = "https://" + strings.TrimPrefix(raw, "webcal://")
	}
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" || u.User != nil || u.Fragment != "" {
		return nil, fmt.Errorf("invalid feed URL")
	}
	if u.Scheme != "https" && !(allowHTTP && u.Scheme == "http") {
		return nil, fmt.Errorf("feed URL must use HTTPS")
	}
	return u, nil
}

func atomicWrite(path string, data []byte, perm os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(path), ".incoming-")
	if err != nil {
		return err
	}
	name := tmp.Name()
	defer os.Remove(name)
	if err := tmp.Chmod(perm); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Sync(); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(name, path)
}

func loadMetadata(path string) metadata {
	var m metadata
	data, err := os.ReadFile(path)
	if err == nil {
		_ = json.Unmarshal(data, &m)
	}
	return m
}

func httpClient(opts UpdateOptions) (*http.Client, error) {
	if opts.Client != nil {
		return opts.Client, nil
	}
	transport := &http.Transport{TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS12}}
	if opts.CAFile != "" {
		pem, err := os.ReadFile(opts.CAFile)
		if err != nil {
			return nil, fmt.Errorf("CA file unavailable")
		}
		pool, err := x509.SystemCertPool()
		if err != nil || pool == nil {
			pool = x509.NewCertPool()
		}
		if !pool.AppendCertsFromPEM(pem) {
			return nil, fmt.Errorf("CA file invalid")
		}
		transport.TLSClientConfig.RootCAs = pool
	}
	return &http.Client{Transport: transport, Timeout: opts.Timeout}, nil
}

// Update downloads a calendar conditionally, renders locally, and only then
// atomically advances the cache, validators, and visible image.
func Update(ctx context.Context, opts UpdateOptions) (UpdateResult, error) {
	if opts.MaxBytes == 0 {
		opts.MaxBytes = 4 << 20
	}
	if opts.Timeout == 0 {
		opts.Timeout = 30 * time.Second
	}
	if opts.Now.IsZero() {
		opts.Now = time.Now()
	}
	u, err := readSecretURL(opts.FeedFile, opts.AllowHTTP)
	if err != nil {
		return UpdateResult{}, err
	}
	m := loadMetadata(opts.MetadataFile)
	client, err := httpClient(opts)
	if err != nil {
		return UpdateResult{}, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), nil)
	if err != nil {
		return UpdateResult{}, fmt.Errorf("request setup failed")
	}
	req.Header.Set("Accept", "text/calendar, text/plain;q=0.8")
	req.Header.Set("User-Agent", "kindle-calendar/1")
	if m.ETag != "" {
		req.Header.Set("If-None-Match", m.ETag)
	}
	if m.LastModified != "" {
		req.Header.Set("If-Modified-Since", m.LastModified)
	}
	resp, err := client.Do(req)
	if err != nil {
		return UpdateResult{}, fmt.Errorf("calendar download failed")
	}
	defer resp.Body.Close()
	result := UpdateResult{HTTPStatus: resp.StatusCode}
	var ics []byte
	switch resp.StatusCode {
	case http.StatusNotModified:
		result.NotModified = true
		ics, err = os.ReadFile(opts.CacheFile)
		if err != nil {
			return result, fmt.Errorf("304 without a cache")
		}
	case http.StatusOK:
		contentType := strings.ToLower(strings.Split(resp.Header.Get("Content-Type"), ";")[0])
		if contentType != "text/calendar" && contentType != "text/plain" && contentType != "application/octet-stream" && contentType != "" {
			return result, fmt.Errorf("unexpected calendar content type")
		}
		limited := io.LimitReader(resp.Body, opts.MaxBytes+1)
		ics, err = io.ReadAll(limited)
		if err != nil {
			return result, fmt.Errorf("calendar body unreadable")
		}
		if int64(len(ics)) > opts.MaxBytes {
			return result, fmt.Errorf("calendar body too large")
		}
	default:
		return result, fmt.Errorf("calendar HTTP status %d", resp.StatusCode)
	}
	if err != nil || !bytes.Contains(ics, []byte("BEGIN:VCALENDAR")) {
		return result, fmt.Errorf("invalid calendar body")
	}
	events, err := ParseICS(string(ics), opts.Location)
	if err != nil {
		return result, fmt.Errorf("calendar parse failed: %w", err)
	}
	var image bytes.Buffer
	err = RenderMonth(&image, events, RenderOptions{Width: opts.Width, Height: opts.Height, Now: opts.Now, Location: opts.Location, FontPaths: opts.FontPaths})
	if err != nil {
		return result, fmt.Errorf("calendar render failed: %w", err)
	}
	if resp.StatusCode == http.StatusOK {
		// Cache first; if the image rename fails the old visible image remains, and
		// the next attempt can safely re-render the new cache after a 304.
		if err := atomicWrite(opts.CacheFile, ics, 0600); err != nil {
			return result, fmt.Errorf("cache write failed")
		}
		m = metadata{ETag: resp.Header.Get("ETag"), LastModified: resp.Header.Get("Last-Modified")}
		meta, _ := json.Marshal(m)
		if err := atomicWrite(opts.MetadataFile, append(meta, '\n'), 0600); err != nil {
			return result, fmt.Errorf("metadata write failed")
		}
	}
	if err := atomicWrite(opts.OutputFile, image.Bytes(), 0644); err != nil {
		return result, fmt.Errorf("image replace failed")
	}
	result.EventCount = len(events)
	return result, nil
}
