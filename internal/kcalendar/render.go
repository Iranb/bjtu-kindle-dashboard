package kcalendar

import (
	"fmt"
	"image"
	"image/color"
	"image/draw"
	"image/png"
	"io"
	"os"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"golang.org/x/image/font"
	"golang.org/x/image/font/gofont/gobold"
	"golang.org/x/image/font/gofont/goregular"
	"golang.org/x/image/font/opentype"
	"golang.org/x/image/math/fixed"
)

type RenderOptions struct {
	Width, Height int
	Now           time.Time
	Location      *time.Location
	FontPaths     []string
	DayInfo       map[string]DayInfo
}

type fontSet struct {
	regular []*opentype.Font
	bold    []*opentype.Font
}

func loadFonts(paths []string) (*fontSet, error) {
	reg, err := opentype.Parse(goregular.TTF)
	if err != nil {
		return nil, err
	}
	bld, err := opentype.Parse(gobold.TTF)
	if err != nil {
		return nil, err
	}
	fs := &fontSet{regular: []*opentype.Font{reg}, bold: []*opentype.Font{bld}}
	for _, path := range paths {
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		f, err := opentype.Parse(data)
		if err == nil {
			// System CJK fonts can serve as a fallback in both weights.
			fs.regular = append([]*opentype.Font{f}, fs.regular...)
			fs.bold = append([]*opentype.Font{f}, fs.bold...)
		}
	}
	return fs, nil
}

type textStyle struct {
	size  float64
	bold  bool
	shade uint8
}

func (fs *fontSet) faces(style textStyle) ([]font.Face, error) {
	fonts := fs.regular
	if style.bold {
		fonts = fs.bold
	}
	var faces []font.Face
	for _, f := range fonts {
		face, err := opentype.NewFace(f, &opentype.FaceOptions{Size: style.size, DPI: 72, Hinting: font.HintingFull})
		if err != nil {
			return nil, err
		}
		faces = append(faces, face)
	}
	return faces, nil
}

func closeFaces(faces []font.Face) {
	for _, face := range faces {
		if c, ok := face.(io.Closer); ok {
			_ = c.Close()
		}
	}
}

func faceForRune(faces []font.Face, r rune) font.Face {
	for _, f := range faces {
		if _, ok := f.GlyphAdvance(r); ok {
			return f
		}
	}
	return faces[len(faces)-1]
}

func textWidth(faces []font.Face, s string) int {
	width := fixed.Int26_6(0)
	for _, r := range s {
		adv, _ := faceForRune(faces, r).GlyphAdvance(r)
		width += adv
	}
	return width.Ceil()
}

func ellipsize(faces []font.Face, s string, max int) string {
	s = strings.ReplaceAll(strings.ReplaceAll(s, "\n", " "), "\r", " ")
	if textWidth(faces, s) <= max {
		return s
	}
	ellipsis := "…"
	for len(s) > 0 && textWidth(faces, s+ellipsis) > max {
		_, n := utf8.DecodeLastRuneInString(s)
		s = s[:len(s)-n]
	}
	return strings.TrimSpace(s) + ellipsis
}

func drawText(img draw.Image, fs *fontSet, x, baseline int, maxWidth int, s string, style textStyle) error {
	faces, err := fs.faces(style)
	if err != nil {
		return err
	}
	defer closeFaces(faces)
	s = ellipsize(faces, s, maxWidth)
	for _, r := range s {
		face := faceForRune(faces, r)
		d := font.Drawer{Dst: img, Src: image.NewUniform(color.Gray{Y: style.shade}), Face: face, Dot: fixed.P(x, baseline)}
		d.DrawString(string(r))
		adv, _ := face.GlyphAdvance(r)
		x += adv.Ceil()
	}
	return nil
}

func fill(img draw.Image, r image.Rectangle, shade uint8) {
	draw.Draw(img, r.Intersect(img.Bounds()), image.NewUniform(color.Gray{Y: shade}), image.Point{}, draw.Src)
}

func line(img draw.Image, x0, y0, x1, y1 int, shade uint8) {
	if x0 == x1 {
		fill(img, image.Rect(x0, y0, x0+1, y1), shade)
		return
	}
	if y0 == y1 {
		fill(img, image.Rect(x0, y0, x1, y0+1), shade)
	}
}

func circle(img *image.Gray, cx, cy, radius int, shade uint8) {
	r2 := radius * radius
	for y := cy - radius; y <= cy+radius; y++ {
		for x := cx - radius; x <= cx+radius; x++ {
			if (x-cx)*(x-cx)+(y-cy)*(y-cy) <= r2 && image.Pt(x, y).In(img.Bounds()) {
				img.SetGray(x, y, color.Gray{Y: shade})
			}
		}
	}
}

func monthGridStart(t time.Time) time.Time {
	first := time.Date(t.Year(), t.Month(), 1, 0, 0, 0, 0, t.Location())
	// Sunday-first, matching Apple Calendar in the supplied reference.
	return first.AddDate(0, 0, -int(first.Weekday()))
}

func dayKey(t time.Time) string { return t.Format("2006-01-02") }

// RenderMonth writes an Apple-inspired, high-contrast six-week month view as
// an 8-bit grayscale PNG suitable for e-ink.
func RenderMonth(w io.Writer, events []Event, opts RenderOptions) error {
	if opts.Width < 600 || opts.Height < 800 || opts.Width > 2000 || opts.Height > 2500 {
		return fmt.Errorf("unsupported canvas size")
	}
	if opts.Location == nil {
		opts.Location = time.Local
	}
	now := opts.Now.In(opts.Location)
	gridStart := monthGridStart(now)
	gridEnd := gridStart.AddDate(0, 0, 42)
	expanded, err := Expand(events, gridStart, gridEnd, 4096)
	if err != nil {
		return err
	}
	byDay := map[string][]Event{}
	for _, e := range expanded {
		start, end := e.Start.In(opts.Location), e.End.In(opts.Location)
		day := time.Date(start.Year(), start.Month(), start.Day(), 0, 0, 0, 0, opts.Location)
		last := end.Add(-time.Nanosecond)
		for !day.After(last) && day.Before(gridEnd) {
			if !day.Before(gridStart) {
				byDay[dayKey(day)] = append(byDay[dayKey(day)], e)
			}
			day = day.AddDate(0, 0, 1)
		}
	}
	for key := range byDay {
		sort.SliceStable(byDay[key], func(i, j int) bool {
			if byDay[key][i].AllDay != byDay[key][j].AllDay {
				return byDay[key][i].AllDay
			}
			return byDay[key][i].Start.Before(byDay[key][j].Start)
		})
	}
	fs, err := loadFonts(opts.FontPaths)
	if err != nil {
		return err
	}
	img := image.NewGray(image.Rect(0, 0, opts.Width, opts.Height))
	fill(img, img.Bounds(), 246)
	margin := opts.Width / 18
	headerH := opts.Height * 15 / 100
	weekH := opts.Height * 5 / 100
	gridTop := headerH + weekH
	gridBottom := opts.Height - margin/2
	cellW := (opts.Width - 2*margin) / 7
	cellH := (gridBottom - gridTop) / 6
	gridRight := margin + cellW*7

	_ = drawText(img, fs, margin, headerH*56/100, opts.Width/2, fmt.Sprintf("%d年%d月", now.Year(), int(now.Month())), textStyle{size: float64(opts.Width) * .055, bold: true, shade: 26})
	// Compact view selector echoes Apple Calendar while remaining monochrome.
	selectorW, selectorH := opts.Width*26/100, headerH*28/100
	sx, sy := gridRight-selectorW, headerH*20/100
	fill(img, image.Rect(sx, sy, sx+selectorW, sy+selectorH), 225)
	labels := []string{"日", "周", "月", "年"}
	segW := selectorW / 4
	fill(img, image.Rect(sx+2*segW, sy, sx+3*segW, sy+selectorH), 175)
	for i, label := range labels {
		_ = drawText(img, fs, sx+i*segW+segW/2-8, sy+selectorH*68/100, segW-8, label, textStyle{size: float64(opts.Width) * .017, bold: i == 2, shade: 40})
	}

	weekdays := []string{"周日", "周一", "周二", "周三", "周四", "周五", "周六"}
	for i, wd := range weekdays {
		_ = drawText(img, fs, margin+i*cellW+cellW/2-20, gridTop-opts.Height/55, cellW-8, wd, textStyle{size: float64(opts.Width) * .018, bold: true, shade: 78})
	}
	for i := 0; i <= 7; i++ {
		line(img, margin+i*cellW, gridTop, margin+i*cellW, gridBottom, 190)
	}
	for i := 0; i <= 6; i++ {
		line(img, margin, gridTop+i*cellH, gridRight, gridTop+i*cellH, 190)
	}

	dateSize := float64(opts.Width) * .025
	eventSize := float64(opts.Width) * .0155
	for idx := 0; idx < 42; idx++ {
		day := gridStart.AddDate(0, 0, idx)
		col, row := idx%7, idx/7
		x, y := margin+col*cellW, gridTop+row*cellH
		inMonth := day.Month() == now.Month()
		shade := uint8(45)
		if !inMonth {
			shade = 150
			fill(img, image.Rect(x+1, y+1, x+cellW, y+cellH), 238)
		}
		today := day.Year() == now.Year() && day.YearDay() == now.YearDay()
		dateX, dateY := x+cellW-42, y+36
		if today {
			circle(img, dateX+13, dateY-9, 22, 35)
			shade = 250
		}
		_ = drawText(img, fs, dateX, dateY, 36, fmt.Sprintf("%d", day.Day()), textStyle{size: dateSize, bold: true, shade: shade})
		info := opts.DayInfo[dayKey(day)]
		if info.LunarLabel != "" {
			lunarShade := uint8(95)
			if !inMonth {
				lunarShade = 165
			}
			_ = drawText(img, fs, x+8, y+31, cellW-58, info.LunarLabel, textStyle{size: float64(opts.Width) * .0145, shade: lunarShade})
		}

		items := byDay[dayKey(day)]
		barY := y + 58
		barH := maxInt(28, cellH/7)
		maxBars := maxInt(1, (cellH-70)/barH)
		barOffset := 0
		if info.HolidayName != "" {
			barShade, textShade, prefix := uint8(74), uint8(250), "休 "
			if info.IsWorkday {
				barShade, textShade, prefix = 218, 32, "班 "
			}
			fill(img, image.Rect(x+5, barY, x+cellW-5, barY+barH-3), barShade)
			_ = drawText(img, fs, x+10, barY+barH-9, cellW-20, prefix+info.HolidayName, textStyle{size: eventSize, bold: true, shade: textShade})
			barOffset = 1
		}
		for j, e := range items {
			if j+barOffset >= maxBars {
				break
			}
			barShade := uint8(214)
			textShade := uint8(25)
			if e.AllDay {
				barShade = 70
				textShade = 250
			}
			itemY := barY + (j+barOffset)*barH
			fill(img, image.Rect(x+5, itemY, x+cellW-5, itemY+barH-3), barShade)
			prefix := ""
			if !e.AllDay {
				prefix = e.Start.In(opts.Location).Format("15:04 ")
			}
			_ = drawText(img, fs, x+10, itemY+barH-9, cellW-20, prefix+e.Title, textStyle{size: eventSize, bold: e.AllDay, shade: textShade})
		}
		visibleEvents := maxBars - barOffset
		if visibleEvents < 0 {
			visibleEvents = 0
		}
		if len(items) > visibleEvents {
			_ = drawText(img, fs, x+10, y+cellH-9, cellW-20, fmt.Sprintf("+%d", len(items)-visibleEvents), textStyle{size: eventSize, bold: true, shade: 80})
		}
	}
	return png.Encode(w, img)
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}
