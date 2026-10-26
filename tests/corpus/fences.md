# Fences

A backtick fence:

```
plain code
```

A tilde fence:

~~~
tilde code
~~~

A fence with an info string:

```python title="demo.py"
def greet(name):
    return f"Hello {name}"
```

A fence holding lines that look like markdown:

```
# not a heading
- not a list item
1. not an ordered item
> not a quote
```

A four-backtick fence holding three backticks:

````md
```
inner fence
```
````

A fence indented under a list item:

- Step one

  ```sh
  echo "indented under the item"
  ```

- Step two

~~~
```
not closed by this
```
~~~

An unclosed fence at the very end of the file:

```text
this fence never closes
# still code, not a heading
