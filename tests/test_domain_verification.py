"""Domain-verification tests.

The booking flow is the one place where a wrong host means a reader hands
their card details to a lookalike. These tests pin the rule: a brand may
only match on a domain-label boundary, never as a substring anywhere in
the hostname.
"""

from __future__ import annotations

import unittest

from public_flight_search.booking_links import (
    provider_domain_matches_label,
    _host_matches_suffixes,
)
from public_flight_search.verification import (
    provider_domain_matches_label as verification_matcher,
)


class TestBrandEmbeddingIsRejected(unittest.TestCase):
    """A hostname that merely CONTAINS a brand must not pass."""

    def test_embedded_brand_before_a_real_domain_is_rejected(self):
        self.assertFalse(
            provider_domain_matches_label("Kayak", "https://kayak.co.uk.attacker.example/flights")
        )

    def test_embedded_brand_after_a_subdomain_is_rejected(self):
        self.assertFalse(
            provider_domain_matches_label(
                "Emirates", "https://www.emirates.com.attacker.net/book"
            )
        )

    def test_brand_in_a_subdomain_of_an_attacker_domain_is_rejected(self):
        self.assertFalse(
            provider_domain_matches_label(
                "Gulf Air", "https://gulfair.attacker.example/"
            )
        )

    def test_unknown_provider_brand_embedded_is_rejected(self):
        self.assertFalse(
            provider_domain_matches_label("Some Airline", "https://someairline.com.attacker.net/")
        )

    def test_brand_as_a_path_segment_does_not_help(self):
        self.assertFalse(
            provider_domain_matches_label("Kayak", "https://attacker.example/kayak.co.uk")
        )


class TestLegitimateHostsPass(unittest.TestCase):
    def test_exact_registrable_domain_passes(self):
        self.assertTrue(provider_domain_matches_label("Kayak", "https://kayak.co.uk/"))

    def test_www_subdomain_passes(self):
        self.assertTrue(provider_domain_matches_label("Kayak", "https://www.kayak.co.uk/"))

    def test_deeper_subdomain_passes(self):
        self.assertTrue(provider_domain_matches_label("Etihad Airways", "https://www.etihad.com/en-gb"))

    def test_unknown_provider_matching_its_own_name_passes(self):
        self.assertTrue(provider_domain_matches_label("Some Airline", "https://someairline.com/"))

    def test_trailing_dot_fqdn_passes(self):
        self.assertTrue(provider_domain_matches_label("Kayak", "https://kayak.co.uk./"))

    def test_empty_and_malformed_inputs_fail_closed(self):
        self.assertFalse(provider_domain_matches_label("Kayak", ""))
        self.assertFalse(provider_domain_matches_label("Kayak", "not a url"))
        self.assertFalse(provider_domain_matches_label("", "https://kayak.co.uk/"))


class TestSuffixHelper(unittest.TestCase):
    def test_requires_a_label_boundary(self):
        self.assertTrue(_host_matches_suffixes("www.example.com", ("example.com",)))
        self.assertTrue(_host_matches_suffixes("example.com", ("example.com",)))
        self.assertFalse(_host_matches_suffixes("example.com.evil.net", ("example.com",)))
        self.assertFalse(_host_matches_suffixes("notexample.com", ("example.com",)))
        self.assertFalse(_host_matches_suffixes("example.com.evil", ("example.com",)))


class TestSingleImplementation(unittest.TestCase):
    """Both modules must apply the SAME rule, including on attack hosts."""

    def test_verification_module_delegates_to_the_strict_matcher(self):
        for provider, url in (
            ("Kayak", "https://kayak.co.uk.attacker.example/"),
            ("Kayak", "https://www.kayak.co.uk/"),
            ("Emirates", "https://www.emirates.com.attacker.net/"),
            ("Emirates", "https://www.emirates.com/uk/english/"),
            ("Gulf Air", "https://gulfair.attacker.example/"),
        ):
            with self.subTest(provider=provider, url=url):
                self.assertEqual(
                    provider_domain_matches_label(provider, url),
                    verification_matcher(provider, url),
                )

    def test_the_two_matchers_no_longer_disagree_on_an_embedding_attack(self):
        # Pre-fix, verification.py accepted this host and booking_links.py
        # rejected it. Divergent copies of a security rule are the bug.
        attack = "https://kayak.co.uk.attacker.example/flights"
        self.assertFalse(provider_domain_matches_label("Kayak", attack))
        self.assertFalse(verification_matcher("Kayak", attack))


class TestUnverifiedConstantIsDefined(unittest.TestCase):
    def test_status_constant_exists_before_use(self):
        from public_flight_search import verification

        self.assertEqual(verification.UNVERIFIED, "UNVERIFIED")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
