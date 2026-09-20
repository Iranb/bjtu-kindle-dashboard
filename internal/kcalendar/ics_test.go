package kcalendar

import (
	"strings"
	"testing"
	"time"
)

const sampleICS = "BEGIN:VCALENDAR\r\n" +
	"VERSION:2.0\r\n" +
	"BEGIN:VEVENT\r\n" +
	"UID:weekly-1\r\n" +
	"DTSTART;TZID=Asia/Shanghai:20260803T090000\r\n" +
	"DTEND;TZID=Asia/Shanghai:20260803T100000\r\n" +
	"RRULE:FREQ=WEEKLY;COUNT=4\r\n" +
	"EXDATE;TZID=Asia/Shanghai:20260817T090000\r\n" +
	"SUMMARY:Research\\, meeting\r\n" +
	"DESCRIPTION:must never be retained\r\n" +
	"LOCATION:private room\r\n" +
	"END:VEVENT\r\n" +
	"BEGIN:VEVENT\r\n" +
	"UID:deadline\r\n" +
	"DTSTART;VALUE=DATE:20260818\r\n" +
	"DTEND;VALUE=DATE:20260819\r\n" +
	"SUMMARY:AAAI deadline\r\n" +
	"END:VEVENT\r\n" +
	"END:VCALENDAR\r\n"

func TestParseAndExpand(t *testing.T) {
	loc, _ := time.LoadLocation("Asia/Shanghai")
	events, err := ParseICS(sampleICS, loc)
	if err != nil {
		t.Fatal(err)
	}
	if len(events) != 2 {
		t.Fatalf("events=%d", len(events))
	}
	if events[0].Title != "Research, meeting" {
		t.Fatalf("title=%q", events[0].Title)
	}
	if strings.Contains(events[0].Title, "private") {
		t.Fatal("private non-summary data leaked")
	}
	from := time.Date(2026, 8, 1, 0, 0, 0, 0, loc)
	to := time.Date(2026, 9, 1, 0, 0, 0, 0, loc)
	expanded, err := Expand(events, from, to, 20)
	if err != nil {
		t.Fatal(err)
	}
	if len(expanded) != 4 {
		t.Fatalf("expanded=%d want 4", len(expanded))
	}
	for _, e := range expanded {
		if e.Start.Day() == 17 {
			t.Fatal("EXDATE occurrence was not removed")
		}
	}
}

func TestFoldedLineAndDefaultDuration(t *testing.T) {
	ics := "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:x\nDTSTART:20260801T120000Z\nSUMMARY:Long \n title\nEND:VEVENT\nEND:VCALENDAR\n"
	events, err := ParseICS(ics, time.UTC)
	if err != nil {
		t.Fatal(err)
	}
	if events[0].Title != "Long title" {
		t.Fatalf("title=%q", events[0].Title)
	}
	if events[0].End.Sub(events[0].Start) != time.Hour {
		t.Fatal("default duration mismatch")
	}
}

func TestRejectMalformedCalendar(t *testing.T) {
	_, err := ParseICS("BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:x\nEND:VEVENT\nEND:VCALENDAR\n", time.UTC)
	if err == nil {
		t.Fatal("expected missing DTSTART error")
	}
}
