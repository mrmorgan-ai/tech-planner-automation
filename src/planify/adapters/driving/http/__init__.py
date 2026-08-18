"""The HTTP driving adapter: the same use cases, over the wire.

Transport and process lifecycle only. Every rule this adapter appears to
enforce — the approval gate above all — is enforced in the use cases and the
domain, so nothing here can be routed around by calling a different endpoint.
"""
