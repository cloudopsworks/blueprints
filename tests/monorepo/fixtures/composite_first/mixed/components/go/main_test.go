package main
import "testing"
func TestMessage(t *testing.T) { if message() != "ok" { t.Fatal("message") } }
