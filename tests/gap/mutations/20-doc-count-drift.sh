MUT_DESC="CLAUDE.md agent count drifts from the shipped agent files (silent count-rot)"
MUT_CLAIM="validate.sh doc-accuracy count-drift catcher"
MUT_BASELINE_PASS="Doc-accuracy: CLAUDE.md '13 specialized SDLC/SSDLC agents' matches code"
MUT_EXPECT="Doc-accuracy: CLAUDE.md says '12 specialized SDLC/SSDLC agents' but code has 13"

mutate() {
    mut_replace "$1/CLAUDE.md" \
        '13 specialized SDLC/SSDLC agents' '12 specialized SDLC/SSDLC agents'
}
