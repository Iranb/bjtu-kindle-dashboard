package kcalendar

import (
	"bufio"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	rrule "github.com/teambition/rrule-go"
)

// Event is the privacy-minimal subset used by the Kindle renderer.
type Event struct {
	UID          string
	Title        string
	Start        time.Time
	End          time.Time
	AllDay       bool
	RRULE        string
	RDates       []time.Time
	ExDates      []time.Time
	RecurrenceID *time.Time
}

type property struct {
	Name   string
	Params map[string]string
	Value  string
}

func unfold(input string) ([]string, error) {
	s := bufio.NewScanner(strings.NewReader(strings.ReplaceAll(input, "\r\n", "\n")))
	s.Buffer(make([]byte, 4096), 4<<20)
	var lines []string
	for s.Scan() {
		line := strings.TrimSuffix(s.Text(), "\r")
		if len(line) > 0 && (line[0] == ' ' || line[0] == '\t') {
			if len(lines) == 0 {
				return nil, fmt.Errorf("orphan folded line")
			}
			lines[len(lines)-1] += line[1:]
		} else {
			lines = append(lines, line)
		}
	}
	if err := s.Err(); err != nil {
		return nil, err
	}
	return lines, nil
}

func parseProperty(line string) (property, error) {
	i := strings.IndexByte(line, ':')
	if i <= 0 {
		return property{}, fmt.Errorf("invalid content line")
	}
	left, value := line[:i], line[i+1:]
	parts := strings.Split(left, ";")
	p := property{Name: strings.ToUpper(parts[0]), Params: map[string]string{}, Value: value}
	for _, item := range parts[1:] {
		kv := strings.SplitN(item, "=", 2)
		if len(kv) != 2 || kv[0] == "" {
			return property{}, fmt.Errorf("invalid parameter")
		}
		p.Params[strings.ToUpper(kv[0])] = strings.Trim(kv[1], `"`)
	}
	return p, nil
}

func unescapeText(s string) string {
	var b strings.Builder
	for i := 0; i < len(s); i++ {
		if s[i] != '\\' || i+1 >= len(s) {
			b.WriteByte(s[i])
			continue
		}
		i++
		switch s[i] {
		case 'n', 'N':
			b.WriteByte('\n')
		case '\\', ',', ';':
			b.WriteByte(s[i])
		default:
			b.WriteByte(s[i])
		}
	}
	return strings.TrimSpace(b.String())
}

func parseDateTime(p property, defaultLoc *time.Location) (time.Time, bool, error) {
	value := strings.TrimSpace(p.Value)
	allDay := strings.EqualFold(p.Params["VALUE"], "DATE") || (len(value) == 8 && !strings.Contains(value, "T"))
	if allDay {
		t, err := time.ParseInLocation("20060102", value, defaultLoc)
		return t, true, err
	}
	loc := defaultLoc
	if tzid := p.Params["TZID"]; tzid != "" {
		var err error
		loc, err = time.LoadLocation(tzid)
		if err != nil {
			return time.Time{}, false, fmt.Errorf("unknown TZID")
		}
	}
	if strings.HasSuffix(value, "Z") {
		t, err := time.Parse("20060102T150405Z", value)
		return t, false, err
	}
	for _, layout := range []string{"20060102T150405", "20060102T1504"} {
		if t, err := time.ParseInLocation(layout, value, loc); err == nil {
			return t, false, nil
		}
	}
	return time.Time{}, false, fmt.Errorf("invalid date-time")
}

func parseDateList(p property, defaultLoc *time.Location) ([]time.Time, error) {
	var out []time.Time
	for _, value := range strings.Split(p.Value, ",") {
		q := p
		q.Value = value
		t, _, err := parseDateTime(q, defaultLoc)
		if err != nil {
			return nil, err
		}
		out = append(out, t)
	}
	return out, nil
}

// ParseICS parses VEVENT data without retaining notes, attendees, locations, or
// organizer fields. Invalid events fail the update so the last good image stays.
func ParseICS(data string, defaultLoc *time.Location) ([]Event, error) {
	lines, err := unfold(data)
	if err != nil {
		return nil, err
	}
	if len(lines) == 0 || !strings.EqualFold(lines[0], "BEGIN:VCALENDAR") {
		return nil, fmt.Errorf("not a VCALENDAR")
	}
	var events []Event
	var current *Event
	for _, line := range lines {
		switch strings.ToUpper(line) {
		case "BEGIN:VEVENT":
			if current != nil {
				return nil, fmt.Errorf("nested VEVENT")
			}
			current = &Event{}
			continue
		case "END:VEVENT":
			if current == nil {
				return nil, fmt.Errorf("unexpected END:VEVENT")
			}
			if current.Start.IsZero() {
				return nil, fmt.Errorf("VEVENT missing DTSTART")
			}
			if current.End.IsZero() {
				if current.AllDay {
					current.End = current.Start.AddDate(0, 0, 1)
				} else {
					current.End = current.Start.Add(time.Hour)
				}
			}
			if !current.End.After(current.Start) {
				return nil, fmt.Errorf("VEVENT has non-positive duration")
			}
			if current.Title == "" {
				current.Title = "Busy"
			}
			events = append(events, *current)
			current = nil
			continue
		}
		if current == nil {
			continue
		}
		p, err := parseProperty(line)
		if err != nil {
			return nil, err
		}
		switch p.Name {
		case "UID":
			current.UID = strings.TrimSpace(p.Value)
		case "SUMMARY":
			current.Title = unescapeText(p.Value)
		case "DTSTART":
			current.Start, current.AllDay, err = parseDateTime(p, defaultLoc)
		case "DTEND":
			current.End, _, err = parseDateTime(p, defaultLoc)
		case "DURATION":
			if current.Start.IsZero() {
				err = fmt.Errorf("DURATION before DTSTART")
			} else {
				var d time.Duration
				d, err = parseDuration(p.Value)
				current.End = current.Start.Add(d)
			}
		case "RRULE":
			current.RRULE = strings.TrimSpace(p.Value)
		case "RDATE":
			current.RDates, err = parseDateList(p, defaultLoc)
		case "EXDATE":
			current.ExDates, err = parseDateList(p, defaultLoc)
		case "RECURRENCE-ID":
			var t time.Time
			t, _, err = parseDateTime(p, defaultLoc)
			current.RecurrenceID = &t
		}
		if err != nil {
			return nil, fmt.Errorf("%s: %w", p.Name, err)
		}
	}
	if current != nil {
		return nil, fmt.Errorf("unterminated VEVENT")
	}
	return events, nil
}

func parseDuration(s string) (time.Duration, error) {
	// Calendar event durations are expected to fit in time.Duration. Support the
	// common RFC 5545 week/day/hour/minute/second subset.
	if s == "" || s[0] != 'P' {
		return 0, fmt.Errorf("invalid duration")
	}
	s = s[1:]
	inTime := false
	value := 0
	var total time.Duration
	for _, r := range s {
		if r >= '0' && r <= '9' {
			value = value*10 + int(r-'0')
			continue
		}
		if r == 'T' {
			inTime = true
			continue
		}
		if value == 0 {
			return 0, fmt.Errorf("invalid duration")
		}
		switch r {
		case 'W':
			total += time.Duration(value) * 7 * 24 * time.Hour
		case 'D':
			total += time.Duration(value) * 24 * time.Hour
		case 'H':
			if !inTime {
				return 0, fmt.Errorf("invalid duration")
			}
			total += time.Duration(value) * time.Hour
		case 'M':
			if !inTime {
				return 0, fmt.Errorf("month duration unsupported")
			}
			total += time.Duration(value) * time.Minute
		case 'S':
			if !inTime {
				return 0, fmt.Errorf("invalid duration")
			}
			total += time.Duration(value) * time.Second
		default:
			return 0, fmt.Errorf("invalid duration unit")
		}
		value = 0
	}
	if value != 0 || total <= 0 {
		return 0, fmt.Errorf("invalid duration")
	}
	return total, nil
}

func timeKey(t time.Time) string { return strconv.FormatInt(t.UTC().Unix(), 10) }

// Expand returns concrete occurrences overlapping [from,to), including bounded
// RRULE/RDATE recurrence and RECURRENCE-ID overrides.
func Expand(events []Event, from, to time.Time, max int) ([]Event, error) {
	overrides := map[string]Event{}
	for _, e := range events {
		if e.RecurrenceID != nil && e.UID != "" {
			overrides[e.UID+"\x00"+timeKey(*e.RecurrenceID)] = e
		}
	}
	var out []Event
	appendIfVisible := func(e Event) error {
		if e.End.After(from) && e.Start.Before(to) {
			out = append(out, e)
			if len(out) > max {
				return fmt.Errorf("event limit exceeded")
			}
		}
		return nil
	}
	for _, e := range events {
		if e.RecurrenceID != nil {
			if err := appendIfVisible(e); err != nil {
				return nil, err
			}
			continue
		}
		duration := e.End.Sub(e.Start)
		excluded := map[string]bool{}
		for _, t := range e.ExDates {
			excluded[timeKey(t)] = true
		}
		starts := []time.Time{e.Start}
		if e.RRULE != "" {
			opt, err := rrule.StrToROptionInLocation(e.RRULE, e.Start.Location())
			if err != nil {
				return nil, fmt.Errorf("RRULE: %w", err)
			}
			opt.Dtstart = e.Start
			r, err := rrule.NewRRule(*opt)
			if err != nil {
				return nil, fmt.Errorf("RRULE: %w", err)
			}
			starts = r.Between(from.Add(-duration), to, true)
		}
		starts = append(starts, e.RDates...)
		seen := map[string]bool{}
		for _, start := range starts {
			key := timeKey(start)
			if seen[key] || excluded[key] {
				continue
			}
			seen[key] = true
			if replacement, ok := overrides[e.UID+"\x00"+key]; ok {
				_ = replacement
				continue
			}
			occ := e
			occ.Start, occ.End, occ.RRULE = start, start.Add(duration), ""
			if err := appendIfVisible(occ); err != nil {
				return nil, err
			}
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Start.Equal(out[j].Start) {
			return out[i].Title < out[j].Title
		}
		return out[i].Start.Before(out[j].Start)
	})
	return out, nil
}
