from flask import Flask, render_template, request
import requests
import json

app = Flask(__name__)